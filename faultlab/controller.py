"""Validate, schedule, execute, record, and clean up FaultLab scenarios.

AI-assistance disclosure: this controller was initially developed with OpenAI
Codex on October 22, 2026. It must be reviewed, tested, understood, and cited as
AI-assisted work before being used as a student contribution.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from faultlab.fault_adapters import DryRunFaultExecutor, FaultExecutor, FaultHandle
from faultlab.scenario_validator import (
    ScenarioValidationError,
    ValidationIssue,
    load_and_validate,
    validate_scenario,
)


class Executor(Protocol):
    def apply(self, action: Mapping[str, Any], service: str) -> FaultHandle: ...

    def cleanup(self, handle: FaultHandle) -> None: ...


class ScenarioExecutionError(RuntimeError):
    """Raised after a failed run has been cleaned up and documented."""

    def __init__(self, message: str, summary_path: Path):
        self.summary_path = summary_path
        super().__init__(f"{message} Run summary: {summary_path}")


@dataclass(slots=True)
class EventJournal:
    path: Path
    run_id: str
    scenario_id: str
    now: Callable[[], datetime]
    sequence: int = 0

    def emit(self, event_type: str, **fields: Any) -> dict[str, Any]:
        self.sequence += 1
        event = {
            "sequence": self.sequence,
            "timestamp_utc": self.now().astimezone(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "event_type": event_type,
            **fields,
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")
        return event


def _schedule_issues(document: Mapping[str, Any]) -> list[ValidationIssue]:
    """Reject overlaps so one cleanup cannot accidentally remove another fault."""

    actions = sorted(
        enumerate(document["actions"]),
        key=lambda item: float(item[1]["start_after_seconds"]),
    )
    issues: list[ValidationIssue] = []
    previous_end = -1.0
    previous_id = ""
    for original_index, action in actions:
        start = float(action["start_after_seconds"])
        end = start + float(action["duration_seconds"])
        if start < previous_end:
            issues.append(
                ValidationIssue(
                    f"$.actions[{original_index}]",
                    f"overlaps action {previous_id!r}; FaultLab 1.0 runs one fault at a time",
                )
            )
        if end > previous_end:
            previous_end = end
            previous_id = str(action["id"])
    return issues


def _run_id(scenario_id: str, now: datetime) -> str:
    timestamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{scenario_id}-{timestamp}-{uuid.uuid4().hex[:8]}"


def execute_scenario(
    document: Mapping[str, Any],
    *,
    executor: Executor,
    results_dir: Path,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    time_scale: float = 1.0,
) -> dict[str, Any]:
    """Run a validated scenario and return its persisted summary."""

    issues = validate_scenario(document)
    if not issues:
        issues.extend(_schedule_issues(document))
    if issues:
        raise ScenarioValidationError(issues)
    if not 0 <= time_scale <= 1:
        raise ValueError("time_scale must be between 0 and 1")

    started_utc = now()
    run_id = _run_id(str(document["scenario_id"]), started_utc)
    run_dir = results_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "scenario.json").write_text(
        json.dumps(document, indent=2, sort_keys=True), encoding="utf-8"
    )

    journal = EventJournal(
        run_dir / "events.jsonl",
        run_id,
        str(document["scenario_id"]),
        now,
    )
    target_services = {
        str(target["name"]): str(target["service"])
        for target in document["targets"]
    }
    start_clock = monotonic()
    active: list[FaultHandle] = []
    action_results: list[dict[str, Any]] = []
    failure: BaseException | None = None

    journal.emit(
        "run_started",
        description=document["description"],
        dry_run=time_scale == 0,
        action_count=len(document["actions"]),
    )

    try:
        actions = sorted(
            document["actions"], key=lambda action: float(action["start_after_seconds"])
        )
        for action in actions:
            service = target_services[str(action["target"])]
            planned_start = float(action["start_after_seconds"])
            planned_end = planned_start + float(action["duration_seconds"])
            scaled_due = start_clock + planned_start * time_scale
            wait_seconds = max(0.0, scaled_due - monotonic())
            if wait_seconds:
                sleep(wait_seconds)

            observed_start = monotonic() - start_clock
            journal.emit(
                "fault_apply_started",
                action_id=action["id"],
                fault_type=action["type"],
                target=action["target"],
                service=service,
                planned_offset_seconds=planned_start,
                observed_offset_seconds=observed_start,
                parameters=action["parameters"],
            )

            handle = executor.apply(action, service)
            active.append(handle)
            applied_offset = monotonic() - start_clock
            journal.emit(
                "fault_applied",
                action_id=action["id"],
                fault_type=action["type"],
                target=action["target"],
                service=service,
                planned_offset_seconds=planned_start,
                observed_offset_seconds=applied_offset,
            )

            duration = float(action["duration_seconds"]) * time_scale
            if duration:
                sleep(duration)

            journal.emit(
                "fault_cleanup_started",
                action_id=action["id"],
                fault_type=action["type"],
                target=action["target"],
                service=service,
            )
            executor.cleanup(handle)
            active.remove(handle)
            observed_end = monotonic() - start_clock
            journal.emit(
                "fault_cleaned",
                action_id=action["id"],
                fault_type=action["type"],
                target=action["target"],
                service=service,
                planned_offset_seconds=planned_end,
                observed_offset_seconds=observed_end,
            )
            action_results.append(
                {
                    "action_id": action["id"],
                    "fault_type": action["type"],
                    "target": action["target"],
                    "service": service,
                    "planned_start_seconds": planned_start,
                    "observed_start_seconds": applied_offset,
                    "start_drift_seconds": applied_offset - planned_start * time_scale,
                    "planned_end_seconds": planned_end,
                    "observed_end_seconds": observed_end,
                    "cleanup_verified": True,
                }
            )

    except BaseException as exc:
        failure = exc
        journal.emit("run_failed", error_type=type(exc).__name__, error=str(exc))

    cleanup_errors: list[str] = []
    for handle in reversed(active):
        try:
            executor.cleanup(handle)
            journal.emit(
                "emergency_cleanup_completed",
                action_id=handle.action_id,
                fault_type=handle.fault_type,
                service=handle.service,
            )
        except Exception as exc:
            message = f"{handle.action_id}: {exc}"
            cleanup_errors.append(message)
            journal.emit(
                "emergency_cleanup_failed",
                action_id=handle.action_id,
                fault_type=handle.fault_type,
                service=handle.service,
                error=str(exc),
            )

    status = "passed" if failure is None and not cleanup_errors else "failed"
    finished_utc = now()
    summary = {
        "run_id": run_id,
        "scenario_id": document["scenario_id"],
        "status": status,
        "dry_run": time_scale == 0,
        "started_at": started_utc.astimezone(timezone.utc).isoformat(),
        "finished_at": finished_utc.astimezone(timezone.utc).isoformat(),
        "actions_completed": len(action_results),
        "actions_requested": len(document["actions"]),
        "actions": action_results,
        "cleanup_errors": cleanup_errors,
        "error": str(failure) if failure else None,
        "event_log": "events.jsonl",
        "scenario_snapshot": "scenario.json",
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    journal.emit("run_completed", status=status, summary="summary.json")

    if failure is not None:
        if isinstance(failure, KeyboardInterrupt):
            raise failure
        raise ScenarioExecutionError(str(failure), summary_path) from failure
    if cleanup_errors:
        raise ScenarioExecutionError("One or more cleanup operations failed.", summary_path)
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a bounded FaultLab scenario.")
    parser.add_argument("scenario", type=Path, help="validated JSON scenario to run")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("results/experiments"),
        help="directory for scenario snapshots, event logs, and summaries",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="exercise scheduling and event output instantly without changing Docker",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        document = load_and_validate(args.scenario)
        executor: Executor = DryRunFaultExecutor() if args.dry_run else FaultExecutor()
        summary = execute_scenario(
            document,
            executor=executor,
            results_dir=args.results_dir,
            time_scale=0 if args.dry_run else 1,
        )
    except (ScenarioValidationError, ScenarioExecutionError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    mode = "dry run" if args.dry_run else "live run"
    print(f"FaultLab {mode} passed: {summary['run_id']}")
    print(f"Results: {args.results_dir / summary['run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
