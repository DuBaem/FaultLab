"""Run local fault-safety checks, separate from recording/replay evaluation.

AI-assisted with OpenAI Codex, November 20, 2026. Only use against the local
FaultLab Compose stack, with no other fault controller running.
"""

from __future__ import annotations

import argparse
import csv
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from faultlab.controller import execute_scenario
from faultlab.docker_cli import DockerCompose
from faultlab.fault_adapters import FaultExecutor


ROOT = Path(__file__).resolve().parents[1]
FAULT_PARAMETERS = {
    "latency": {"latency_ms": 250, "jitter_ms": 0},
    "packet_loss": {"loss_percent": 100},
    "disconnect": {"direction": "both"},
    "process_failure": {"signal": "SIGKILL"},
}
# The probe runs inside the baseline image so it can check replies the same way as the baseline.
PROBE_CODE = """
import json, time, sys
from datetime import datetime, timezone
from baseline import run_request, calculate_summary
results = []
for index in range(int(sys.argv[1])):
    started = datetime.now(timezone.utc).isoformat()
    result = run_request(sys.argv[2], f'qa-{index}', 10, 1.0)
    result['started_at'] = started
    result['finished_at'] = datetime.now(timezone.utc).isoformat()
    results.append(result)
    time.sleep(0.05)
print(json.dumps({'results': results, 'summary': calculate_summary(results)}))
"""


def make_scenario(fault_type: str, duration: float = 8) -> dict:
    return {
        "schema_version": "1.0", "scenario_id": f"qa-{fault_type.replace('_', '-')}",
        "description": f"Check how the server responds during {fault_type} and after cleanup.",
        "targets": [{"name": "api-server", "service": "server"}],
        "actions": [{"id": "safety-fault", "type": fault_type, "target": "api-server",
                     "start_after_seconds": 0, "duration_seconds": duration,
                     "parameters": FAULT_PARAMETERS[fault_type]}],
        "expected_outcomes": ["Requests show the effect of the fault, then succeed again after cleanup."],
        "safety": {"scope": "local_docker_only", "cleanup_required": True,
                   "max_total_duration_seconds": 30},
    }


def evaluate_trial(fault_type: str, before: dict, during: dict, after: dict,
                   run: dict, fault_window: tuple[str, str], clean: bool) -> dict:
    """Check what the client experienced during the fault and after cleanup."""
    def all_succeeded(batch):
        results = batch["results"]
        return bool(results) and all(row["success"] for row in results)

    started, ended = (datetime.fromisoformat(value) for value in fault_window)
    inside = [row for row in during["results"]
              if started <= datetime.fromisoformat(row["started_at"])
              <= datetime.fromisoformat(row["finished_at"]) <= ended]
    base_mean = before["summary"]["latency_ms"]["mean"]
    latencies = [row["latency_ms"] for row in inside
                 if row["success"] and row["latency_ms"] is not None]
    observed_mean = sum(latencies) / len(latencies) if latencies else None
    effect_observed = (
        observed_mean is not None and base_mean is not None
        and observed_mean >= base_mean + 100
        if fault_type == "latency" else any(not row["success"] for row in inside)
    )
    checks = {
        "baseline_success": all_succeeded(before),
        "during_samples_inside_fault": bool(inside) and len(inside) == len(during["results"]),
        "fault_effect_observed": effect_observed,
        "controller_passed": run["status"] == "passed",
        "cleanup_verified": bool(run["actions"]) and all(
            row["cleanup_verified"] for row in run["actions"]),
        "service_state_restored": clean,
        "recovery_success": all_succeeded(after),
    }
    return {"passed": all(checks.values()), "checks": checks,
            "baseline_mean_ms": base_mean, "during_success_mean_ms": observed_mean,
            "during_failures": sum(not row["success"] for row in inside),
            "during_sample_count": len(inside),
            "recovery_successes": sum(row["success"] for row in after["results"]),
            "recovery_requests": len(after["results"])}


class SignallingExecutor(FaultExecutor):
    def __init__(self, docker):
        super().__init__(docker)
        self.applied = threading.Event()

    def apply(self, action, service):
        handle = super().apply(action, service)
        self.applied.set()
        return handle


def measure(docker, probe_name, count, server_url="http://server:5000"):
    response = docker.docker(["exec", probe_name, "python", "-c", PROBE_CODE,
                              str(count), server_url])
    return json.loads(response.stdout)


def probe_address(docker, probe_name):
    """Avoid resolver retries extending an HTTP timeout during an outage.

    Recovery is still measured using the server alias, so a broken DNS alias
    after reconnection cannot be mistaken for successful recovery.
    """
    template = "{{json .NetworkSettings.Networks}}"
    server = json.loads(docker.docker([
        "inspect", "--format", template, docker.container_id("server")]).stdout)
    probe = json.loads(docker.docker(["inspect", "--format", template, probe_name]).stdout)
    shared = sorted(set(server) & set(probe))
    if not shared or not server[shared[0]]["IPAddress"]:
        raise RuntimeError("The QA probe and server need a shared IPv4 Docker network")
    return f"http://{server[shared[0]]['IPAddress']}:5000"


def restored_state(docker, expected_networks):
    docker.wait_until_healthy("server")
    queue = docker.exec("server", ["tc", "qdisc", "show", "dev", "eth0"]).stdout
    networks = docker.docker([
        "inspect", "--format", "{{json .NetworkSettings.Networks}}",
        docker.container_id("server")]).stdout
    return "netem" not in queue.lower() and set(json.loads(networks)) == expected_networks


def run_checks(trials: int, results_dir: Path) -> tuple[Path, dict]:
    docker = DockerCompose()
    docker.wait_until_healthy("server")
    networks = set(json.loads(docker.docker([
        "inspect", "--format", "{{json .NetworkSettings.Networks}}",
        docker.container_id("server")]).stdout))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = results_dir / f"fault-safety-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    probe = f"faultlab-qa-{uuid.uuid4().hex[:8]}"
    report = {"started_at": datetime.now(timezone.utc).isoformat(),
              "scope": "local Docker fault safety; not replay reproducibility",
              "trials_per_fault": trials, "trials": [], "interruption": None}
    # The probe stays on the Compose network while the server is disconnected.
    # A short-lived container is removed in finally, even after a failed check.
    try:
        docker.compose(["run", "-d", "--no-deps", "--name", probe,
                        "baseline", "python", "-c", "import time; time.sleep(900)"])
        for trial in range(1, trials + 1):
            for fault_type in FAULT_PARAMETERS:
                print(f"Trial {trial}: {fault_type}", flush=True)
                address = probe_address(docker, probe)
                before = measure(docker, probe, 8, address)
                executor = SignallingExecutor(docker)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(execute_scenario, make_scenario(fault_type),
                                         executor=executor, results_dir=output / "runs")
                    if not executor.applied.wait(35):
                        # Surface an application error, rather than leaving a worker behind.
                        future.result(timeout=90)
                        raise RuntimeError("Fault was not applied within 35 seconds")
                    during = measure(docker, probe, 3, address)
                    run = future.result(timeout=90)
                clean = restored_state(docker, networks)
                after = measure(docker, probe, 8)
                events = [json.loads(line) for line in
                          (output / "runs" / run["run_id"] / "events.jsonl").read_text().splitlines()]
                # Once cleanup starts, a request may already see a recovering server.
                window = tuple(next(e["timestamp_utc"] for e in events if e["event_type"] == kind)
                               for kind in ("fault_applied", "fault_cleanup_started"))
                evaluation = evaluate_trial(fault_type, before, during, after, run, window, clean)
                report["trials"].append({"trial": trial, "fault_type": fault_type,
                                         "run_id": run["run_id"], "before": before,
                                         "fault_probe_url": address,
                                         "during": during, "after": after,
                                         "evaluation": evaluation})
                print(f"  {'PASS' if evaluation['passed'] else 'FAIL'} {evaluation}", flush=True)
                (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

        def interrupt_after_apply(seconds):
            time.sleep(min(seconds, 1))
            raise KeyboardInterrupt("controlled QA interruption")

        interrupted = False
        try:
            execute_scenario(make_scenario("latency"), executor=FaultExecutor(docker),
                             results_dir=output / "interrupted", sleep=interrupt_after_apply)
        except KeyboardInterrupt:
            interrupted = True
        summary_file = next((output / "interrupted").glob("*/summary.json"))
        interrupted_run = json.loads(summary_file.read_text())
        recovered = measure(docker, probe, 8)
        report["interruption"] = {
            "run_id": interrupted_run["run_id"],
            "passed": interrupted and interrupted_run["status"] == "failed"
                      and not interrupted_run["cleanup_errors"]
                      and restored_state(docker, networks)
                      and all(row["success"] for row in recovered["results"]),
            "recovery": recovered,
        }
        report["passed"] = all(row["evaluation"]["passed"] for row in report["trials"]) \
                           and report["interruption"]["passed"]
    except BaseException as exc:
        report["passed"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        try:
            (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        finally:
            docker.docker(["rm", "-f", probe], check=False)
    with (output / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = ["trial", "fault_type", "run_id", "passed", "baseline_mean_ms",
                  "during_success_mean_ms", "during_failures", "during_sample_count",
                  "recovery_successes", "recovery_requests"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in report["trials"]:
            writer.writerow({**{key: row[key] for key in ("trial", "fault_type", "run_id")},
                             **{key: row["evaluation"][key] for key in fields[3:]}})
    return output, report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Measure requests before, during, and after faults on the local FaultLab server."
    )
    parser.add_argument("--trials", type=int, choices=range(1, 6), default=2,
                        help="how many times to run each of the four faults (default: 2)")
    parser.add_argument("--results-dir", type=Path, default=Path("results/fault-safety"),
                        help="where to save the trial table, request details, and event logs")
    args = parser.parse_args(argv)
    output, report = run_checks(args.trials, args.results_dir)
    print(f"Fault safety {'PASSED' if report['passed'] else 'FAILED'}: {output}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
