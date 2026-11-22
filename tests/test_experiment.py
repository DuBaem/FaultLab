import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from faultlab import experiment
from faultlab.controller import execute_scenario
from faultlab.fault_adapters import DryRunFaultExecutor
from faultlab.local_stack import CheckedExecutor, ensure_local_engine, stack_lock
from faultlab.report import write_report
from faultlab.scenario_validator import load_and_validate


@pytest.fixture(autouse=True)
def isolate_stack_lock(tmp_path, monkeypatch):
    monkeypatch.setattr("faultlab.local_stack.tempfile.gettempdir", lambda: str(tmp_path))


def test_controller_measures_dispatch_confirmation_and_cleanup(tmp_path):
    scenario = load_and_validate(Path("scenarios/demo-latency-packet-loss.json"))
    clock = [0.0]

    def sleep(dt):
        clock[0] += dt

    class SlowCommands(DryRunFaultExecutor):
        def apply(self, action, service):
            sleep(0.5)
            return super().apply(action, service)

        def cleanup(self, handle):
            sleep(0.8)
            super().cleanup(handle)

    report = execute_scenario(scenario, executor=SlowCommands(), results_dir=tmp_path,
                              monotonic=lambda: clock[0], sleep=sleep)
    first, second = report["actions"]
    assert first["dispatch_seconds"] == 1
    assert first["observed_start_seconds"] == 1.5
    assert first["cleanup_started_seconds"] == 5.5
    assert second["dispatch_drift_seconds"] == pytest.approx(0.3)
    assert second["start_drift_seconds"] == pytest.approx(0.8)
    assert second["apply_overhead_seconds"] == pytest.approx(0.5)


def stamp(n):
    return datetime.fromtimestamp(n, timezone.utc).isoformat()


@pytest.mark.parametrize("start,end,expected", [
    (0, 0.1, ("baseline", None)), (1.1, 1.8, ("applying", "lat")),
    (2.1, 3.9, ("during", "lat")), (1.9, 2.1, ("boundary", None)),
    (3, 5, ("boundary", None)), (4.1, 4.8, ("cleaning", "lat")),
    (5.1, 6, ("between", None)), (7.1, 7.2, ("recovery", None)),
])
def test_attribute_whole_request(start, end, expected):
    events = [{"timestamp_utc": stamp(t), "event_type": name, "action_id": "lat", "status": "passed"}
              for t, name in [(1, "fault_apply_started"), (2, "fault_applied"),
                              (4, "fault_cleanup_started"), (5, "fault_cleaned"), (7, "run_completed")]]
    assert experiment.phase_at(stamp(start), stamp(end), events) == expected


def test_no_matched_failures_is_undefined_and_unmatched_requests_count():
    def report(successes):
        return {"run_id": "same-scenario", "observations": [
            {"phase": "during", "action_id": "a", "success": ok} for ok in successes]}
    row = experiment.compare(report([True, False]), report([True]))
    assert row["matched_requests"] == 1
    assert row["original_requests"] == 2
    assert row["failure_reproduction_percent"] is None
    row = experiment.compare(report([False, True, False]), report([False, True, True]))
    assert row["failure_reproduction_percent"] == 50


def test_refuses_concurrent_operations_and_releases_lock():
    with stack_lock():
        with pytest.raises(RuntimeError, match="Another FaultLab"):
            with stack_lock():
                pytest.fail("Concurrent access")
    with stack_lock():
        pass


def test_malformed_replay_is_rejected_before_using_docker(tmp_path, monkeypatch):
    scenario = load_and_validate(Path("scenarios/valid-latency.json"))
    original = {"scenario": scenario, "run_id": "original", "passed": True,
                "observations": [{"phase": "during", "action_id": "latency"}]}
    run = Mock()
    monkeypatch.setattr(experiment, "run_trial", run)
    with pytest.raises(ValueError, match="incomplete request"):
        experiment.run_series(scenario, original=original, results_dir=tmp_path)
    run.assert_not_called()


def test_remote_engine_rejected_before_running_a_fault(monkeypatch):
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "ssh://remote")
    with pytest.raises(RuntimeError, match="local"):
        ensure_local_engine(Mock())


def test_network_alias_loss_blocks_next_action():
    executor = CheckedExecutor.__new__(CheckedExecutor)
    executor.expected_networks = {"default": ("network-id", True)}
    executor.networks = lambda: {"default": ("network-id", False)}
    with pytest.raises(RuntimeError, match="networks changed"):
        executor.verify(queue_checked=True)


def test_series_stops_and_writes_failure_on_unsuccessful_recovery(tmp_path, monkeypatch):
    scenario = load_and_validate(Path("scenarios/valid-latency.json"))
    run = {"run_id": "example", "scenario": scenario, "actions": [], "passed": False,
           "observations": [], "baseline": experiment.metrics([]), "recovery": experiment.metrics([])}
    mock = Mock(return_value=run)
    monkeypatch.setattr(experiment, "run_trial", mock)
    with pytest.raises(RuntimeError, match="Recovery requests"):
        experiment.run_series(scenario, 10, results_dir=tmp_path)
    assert mock.call_count == 1
    path = next(tmp_path.glob("*/series.json"))
    assert json.loads(path.read_text())["status"] == "failed"
    assert path.with_name("report.html").is_file()


def test_escaped_failure_in_offline_report(tmp_path):
    overview = {"requested_trials": 1, "status": "failed", "error": "<unexpected>", "comparisons": []}
    write_report(tmp_path / "report.html", overview, [])
    assert "&lt;unexpected&gt;" in (tmp_path / "report.html").read_text(encoding="utf-8")
