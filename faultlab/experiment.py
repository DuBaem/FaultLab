"""Run a measured scenario on the local demo stack and save a repeatable report."""

import argparse
import json
import statistics
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from baseline.baseline import calculate_summary, run_request
from faultlab.controller import ScenarioExecutionError, check_schedule, execute_scenario
from faultlab.local_stack import CheckedExecutor, LOCAL_URL, stack_lock
from faultlab.report import write_report
from faultlab.scenario_validator import load_and_validate

ROOT = Path(__file__).resolve().parents[1]
SERIES_DIR = ROOT / "results" / "series"


def save(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def phase_at(start, end, events):
    """A request has one phase only if both endpoints fall inside that phase."""
    phase, action_id = "baseline", None
    edges = {
        "fault_apply_started": "applying", "fault_applied": "during",
        "fault_cleanup_started": "cleaning", "fault_cleaned": "between",
        "emergency_cleanup_completed": "between", "emergency_cleanup_failed": "unverified",
        "run_failed": "unverified",
    }
    for event in events:
        kind = event["event_type"]
        if kind == "run_completed":
            new_phase = "recovery" if event.get("status") == "passed" else "unverified"
        elif kind in edges:
            new_phase = edges[kind]
        else:
            continue
        stamp = event["timestamp_utc"]
        if stamp > end:
            break
        if stamp > start:
            return "boundary", None
        phase = new_phase
        action_id = event.get("action_id") if phase in {"during", "applying", "cleaning"} else None
    return phase, action_id


def metrics(rows):
    summary = calculate_summary(rows)
    summary["timeouts"] = sum(row["timed_out"] for row in rows)
    return summary


def compare(original, repeat):
    """Pair identical workload inputs by action and ordinal inside its confirmed window."""
    def groups(report):
        by_action = {}
        for row in report["observations"]:
            if row["phase"] == "during":
                by_action.setdefault(row["action_id"], []).append(row)
        return by_action

    first, second = groups(original), groups(repeat)
    pairs = [pair for key in first for pair in zip(first[key], second.get(key, []))]
    failures = sum(not a["success"] for a, b in pairs)
    reproduced = sum(not a["success"] and not b["success"] for a, b in pairs)
    return {
        "original_run_id": original["run_id"], "repeat_run_id": repeat["run_id"],
        "matched_requests": len(pairs), "original_requests": sum(map(len, first.values())),
        "repeat_requests": sum(map(len, second.values())),
        "matching_outcomes": sum(a["success"] == b["success"] for a, b in pairs),
        "matched_original_failures": failures, "reproduced_failures": reproduced,
        "failure_reproduction_percent": 100 * reproduced / failures if failures else None,
    }


def aggregate(trials):
    groups = {}
    for trial in trials:
        for action in trial["actions"]:
            groups.setdefault(action["action_id"], []).append(action)
    result = {}
    for name, actions in groups.items():
        means = [a["observed"]["latency_ms"]["mean"] for a in actions
                 if a["observed"]["latency_ms"]["mean"] is not None]
        errors = [abs(a["start_drift_seconds"]) for a in actions]
        result[name] = {
            "trials": len(actions),
            "mean_absolute_start_error_ms": 1000 * statistics.mean(errors),
            "mean_latency_stddev_between_trials_ms": statistics.stdev(means) if len(means) > 1 else None,
            "trials_with_failures": sum(a["observed"]["failed_requests"] > 0 for a in actions),
            "trials_with_observations": sum(a["observed"]["total_requests"] > 0 for a in actions),
            "failures": sum(a["observed"]["failed_requests"] for a in actions),
            "timeouts": sum(a["observed"]["timeouts"] for a in actions),
        }
    return result


def run_trial(document, path, notify, stop):
    executor = CheckedExecutor()
    rows, events = [], []
    done = threading.Event()

    def measure():
        row = run_request(LOCAL_URL, f"req-{len(rows):04}", 10, 1)
        rows.append(row)
        notify("request", row)
        return row

    def observe():
        while not done.is_set():
            measure()
            done.wait(0.15)

    def record(event):
        events.append(event)
        notify("event", event)
        if event["event_type"] == "fault_apply_started" and stop.is_set():
            raise InterruptedError("Experiment stopped by operator")

    def wait(seconds):
        if stop.wait(seconds):
            raise InterruptedError("Experiment stopped by operator")

    baseline = [measure() for _ in range(4)]
    if not all(r["success"] for r in baseline):
        raise RuntimeError("Baseline failed before injection. Check the server and reset.")
    with ThreadPoolExecutor(max_workers=1) as pool:
        sampler = pool.submit(observe)
        try:
            summary = execute_scenario(document, executor=executor, results_dir=path,
                                       sleep=wait, on_event=record)
        finally:
            done.set()
            sampler.result()
            # Even on interruption, preserve request records alongside the controller log.
            if events:
                run_id = events[0]["run_id"]
                for row in rows:
                    row["phase"], row["action_id"] = phase_at(row["started_at"], row["finished_at"], events)
                save(path / run_id / "observations.json", {"run_id": run_id, "observations": rows})

    recovery = [measure() for _ in range(4)]
    for row in recovery:
        row["phase"], row["action_id"] = "recovery", None
    settings = {a["id"]: a["parameters"] for a in document["actions"]}
    actions = []
    for action in summary["actions"]:
        selected = [r for r in rows if r["phase"] == "during" and r["action_id"] == action["action_id"]]
        actions.append({**action, "configured": settings[action["action_id"]], "observed": metrics(selected),
                        "observation_status": "sampled" if selected else "no request fully inside window"})
    run_id = summary["run_id"]
    report = {
        "run_id": run_id, "scenario": document, "actions": actions, "events": events,
        "observations": rows, "baseline": metrics([r for r in rows if r["phase"] == "baseline"]),
        "recovery": metrics(recovery),
        "boundary_requests": sum(r["phase"] == "boundary" for r in rows),
        "passed": all(r["success"] for r in recovery),
    }
    save(path / run_id / "observations.json", {"run_id": run_id, "observations": rows})
    save(path / run_id / "experiment.json", report)
    return report


def run_series(document, trials=1, *, original=None, results_dir=SERIES_DIR,
               notify=lambda kind, value: None, stop=None):
    if not isinstance(trials, int) or not 1 <= trials <= 10:
        raise ValueError("Choose 1 to 10 trials.")
    check_schedule(document)
    if original is not None:
        if (not isinstance(original, dict) or original.get("scenario") != document
                or original.get("passed") is not True or not isinstance(original.get("run_id"), str)
                or not isinstance(original.get("observations"), list)):
            raise ValueError("Replay needs experiment.json from a successful measured run with the same scenario.")
        if any(not isinstance(row, dict) or not isinstance(row.get("phase"), str)
               or (row["phase"] == "during" and
                   (not isinstance(row.get("action_id"), str) or not isinstance(row.get("success"), bool)))
               for row in original["observations"]):
            raise ValueError("The saved experiment has incomplete request observations.")
    stop = stop or threading.Event()
    with stack_lock():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = results_dir / f"{stamp}-{uuid.uuid4().hex[:8]}"
        path.mkdir(parents=True)
        reports = []
        overview = {"requested_trials": trials, "status": "running", "runs": [], "comparisons": []}
        save(path / "series.json", overview)
        try:
            for index in range(trials):
                if stop.is_set():
                    raise InterruptedError("Experiment stopped by operator")
                notify("trial", (index + 1, trials))
                report = run_trial(document, path, notify, stop)
                reports.append(report)
                overview["runs"].append(report["run_id"])
                overview["metrics"] = aggregate(reports)
                reference = original or reports[0]
                if reference is not report:
                    overview["comparisons"].append(compare(reference, report))
                notify("result", report)
                save(path / "series.json", overview)
                if not report["passed"]:
                    raise RuntimeError("Recovery requests failed. Reset before another trial.")
            overview["status"] = "passed"
        except BaseException as exc:
            overview["status"] = "failed"
            overview["error"] = str(exc) or type(exc).__name__
            if isinstance(exc, ScenarioExecutionError):
                overview["failed_run_id"] = exc.summary_path.parent.name
            raise
        finally:
            save(path / "series.json", overview)
            write_report(path / "report.html", overview, reports)
            notify("saved", str(path))
    return path, overview


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--scenario", type=Path, help="a validated local FaultLab scenario")
    choice.add_argument("--replay", type=Path, help="experiment.json from a previous measured run")
    parser.add_argument("--trials", type=int, choices=range(1, 11), default=1)
    args = parser.parse_args()
    original = json.loads(args.replay.read_text(encoding="utf-8")) if args.replay else None
    document = original["scenario"] if original is not None else load_and_validate(args.scenario)
    def progress(kind, value):
        if kind in {"trial", "saved"}:
            print(kind, value, flush=True)
    _, report = run_series(document, args.trials, original=original, notify=progress)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
