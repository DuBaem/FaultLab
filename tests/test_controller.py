"""Tests for timed scenario execution, event output, and emergency cleanup."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from faultlab.controller import EventJournal, ScenarioExecutionError, execute_scenario
from faultlab.fault_adapters import DryRunFaultExecutor
from faultlab.scenario_validator import ScenarioValidationError


ROOT = Path(__file__).resolve().parents[1]


def load_scenario(name: str) -> dict:
    return json.loads((ROOT / "scenarios" / name).read_text(encoding="utf-8"))


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class ScenarioControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.now = lambda: datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)

    def test_two_fault_demo_follows_planned_schedule_and_writes_bundle(self) -> None:
        scenario = load_scenario("demo-latency-packet-loss.json")
        executor = DryRunFaultExecutor()

        with tempfile.TemporaryDirectory(dir=ROOT / "results") as directory:
            summary = execute_scenario(
                scenario,
                executor=executor,
                results_dir=Path(directory),
                monotonic=self.clock.monotonic,
                sleep=self.clock.sleep,
                now=self.now,
            )
            run_dir = Path(directory) / summary["run_id"]
            events = [
                json.loads(line)
                for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
            ]

            self.assertEqual("passed", summary["status"])
            self.assertEqual(2, summary["actions_completed"])
            self.assertEqual(
                ["add-250ms-delay", "drop-25-percent"],
                [handle.action_id for handle in executor.applied],
            )
            self.assertEqual(2, len(executor.cleaned))
            self.assertTrue((run_dir / "scenario.json").exists())
            self.assertTrue((run_dir / "summary.json").exists())
            self.assertEqual(
                [1.0, 6.0],
                [action["observed_start_seconds"] for action in summary["actions"]],
            )
            self.assertIn("fault_applied", [event["event_type"] for event in events])
            self.assertIn("fault_cleaned", [event["event_type"] for event in events])

    def test_overlapping_actions_are_rejected_before_execution(self) -> None:
        scenario = load_scenario("demo-latency-packet-loss.json")
        scenario["actions"][1]["start_after_seconds"] = 2

        with tempfile.TemporaryDirectory(dir=ROOT / "results") as directory:
            with self.assertRaisesRegex(ScenarioValidationError, "overlaps"):
                execute_scenario(
                    scenario,
                    executor=DryRunFaultExecutor(),
                    results_dir=Path(directory),
                    monotonic=self.clock.monotonic,
                    sleep=self.clock.sleep,
                    now=self.now,
                )

    def test_interrupted_fault_is_cleaned_and_failure_is_documented(self) -> None:
        scenario = copy.deepcopy(load_scenario("valid-latency.json"))
        scenario["actions"][0]["start_after_seconds"] = 0
        executor = DryRunFaultExecutor()

        def interrupted_sleep(_seconds: float) -> None:
            raise RuntimeError("simulated interruption")

        with tempfile.TemporaryDirectory(dir=ROOT / "results") as directory:
            with self.assertRaises(ScenarioExecutionError) as raised:
                execute_scenario(
                    scenario,
                    executor=executor,
                    results_dir=Path(directory),
                    monotonic=self.clock.monotonic,
                    sleep=interrupted_sleep,
                    now=self.now,
                )

            summary = json.loads(raised.exception.summary_path.read_text(encoding="utf-8"))
            self.assertEqual("failed", summary["status"])
            self.assertEqual(1, len(executor.cleaned))
            self.assertTrue(executor.cleaned[0].cleaned)

    def test_persistent_journal_failure_cannot_skip_fault_cleanup(self) -> None:
        scenario = load_scenario("valid-latency.json")
        scenario["actions"][0]["start_after_seconds"] = 0
        executor = DryRunFaultExecutor()
        real_emit = EventJournal.emit

        def failing_emit(journal, event_type, **fields):
            if executor.applied:
                raise OSError("event disk unavailable")
            return real_emit(journal, event_type, **fields)

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(EventJournal, "emit", failing_emit):
                with self.assertRaises(ScenarioExecutionError) as raised:
                    execute_scenario(scenario, executor=executor,
                                     results_dir=Path(directory), time_scale=0)
            self.assertEqual(1, len(executor.cleaned))
            summary = json.loads(raised.exception.summary_path.read_text())
            self.assertEqual("failed", summary["status"])
            self.assertEqual([], summary["cleanup_errors"])
            self.assertTrue(summary["logging_errors"])

    def test_keyboard_interrupt_cleans_fault_before_propagating(self) -> None:
        scenario = load_scenario("valid-latency.json")
        scenario["actions"][0]["start_after_seconds"] = 0
        executor = DryRunFaultExecutor()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(KeyboardInterrupt):
                execute_scenario(scenario, executor=executor,
                                 results_dir=Path(directory),
                                 sleep=lambda _: (_ for _ in ()).throw(KeyboardInterrupt()))
            self.assertEqual(1, len(executor.cleaned))
            summary = json.loads(next(Path(directory).glob("*/summary.json")).read_text())
            self.assertEqual("failed", summary["status"])

    def test_cleanup_failure_is_recorded_even_when_error_logging_fails(self) -> None:
        scenario = load_scenario("valid-latency.json")
        scenario["actions"][0]["start_after_seconds"] = 0
        executor = DryRunFaultExecutor()
        real_emit = EventJournal.emit

        def failing_emit(journal, event_type, **fields):
            if event_type in {"run_failed", "emergency_cleanup_failed"}:
                raise OSError("event disk unavailable")
            return real_emit(journal, event_type, **fields)

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(executor, "cleanup", side_effect=RuntimeError("cleanup unavailable")):
                with patch.object(EventJournal, "emit", failing_emit):
                    with self.assertRaises(ScenarioExecutionError) as raised:
                        execute_scenario(scenario, executor=executor,
                                         results_dir=Path(directory), time_scale=0)
            summary = json.loads(raised.exception.summary_path.read_text())
            self.assertEqual("failed", summary["status"])
            self.assertIn("cleanup unavailable", summary["cleanup_errors"][0])

    def test_completion_log_failure_does_not_claim_a_pass(self) -> None:
        real_emit = EventJournal.emit

        def failing_emit(journal, event_type, **fields):
            if event_type == "run_completed":
                raise OSError("completion write failed")
            return real_emit(journal, event_type, **fields)

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(EventJournal, "emit", failing_emit):
                with self.assertRaises(ScenarioExecutionError) as raised:
                    execute_scenario(load_scenario("valid-latency.json"),
                                     executor=DryRunFaultExecutor(),
                                     results_dir=Path(directory), time_scale=0)
            summary = json.loads(raised.exception.summary_path.read_text())
            self.assertEqual("failed", summary["status"])
            self.assertEqual(1, summary["actions_completed"])


if __name__ == "__main__":
    unittest.main()
