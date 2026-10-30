
import argparse
import json
from pathlib import Path

from faultlab.controller import execute_scenario
from faultlab.fault_adapters import (
    DryRunFaultExecutor,
    FaultExecutor,
)
from faultlab.scenario_validator import load_and_validate


def replay_experiment(
    original_run_dir,
    results_dir=Path("results/experiments"),
    dry_run=False,
):
    """Re-execute a recorded FaultLab scenario."""

    original_run_dir = Path(original_run_dir)
    results_dir = Path(results_dir)

    scenario_path = original_run_dir / "scenario.json"
    summary_path = original_run_dir / "summary.json"

    if not scenario_path.is_file():
        raise FileNotFoundError(
            f"Original scenario not found: {scenario_path}"
        )

    if not summary_path.is_file():
        raise FileNotFoundError(
            f"Original summary not found: {summary_path}"
        )

    original_summary = json.loads(
        summary_path.read_text(encoding="utf-8")
    )

    if original_summary.get("status") != "passed":
        raise ValueError(
            "Cannot replay an experiment whose "
            "controller execution did not pass."
        )

    scenario = load_and_validate(scenario_path)

    if original_summary.get("scenario_id") != scenario["scenario_id"]:
        raise ValueError(
            "Original summary and scenario IDs do not match."
        )

    executor = (
        DryRunFaultExecutor()
        if dry_run
        else FaultExecutor()
    )

    replay_summary = execute_scenario(
        scenario,
        executor=executor,
        results_dir=results_dir,
        time_scale=0 if dry_run else 1,
    )

    replay_run_dir = results_dir / replay_summary["run_id"]

    metadata = {
        "original_run_id": original_summary["run_id"],
        "replay_run_id": replay_summary["run_id"],
        "scenario_id": scenario["scenario_id"],
        "replay_mode": "dry_run" if dry_run else "live",
    }

    (replay_run_dir / "replay_metadata.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    return replay_summary


def main():
    parser = argparse.ArgumentParser(
        description="Replay a recorded FaultLab experiment."
    )
    parser.add_argument("original_run_dir", type=Path)
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("results/experiments"),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    args = parser.parse_args()

    summary = replay_experiment(
        args.original_run_dir,
        results_dir=args.results_dir,
        dry_run=args.dry_run,
    )

    print(f"Replay completed: {summary['run_id']}")
    print(f"Status: {summary['status']}")


if __name__ == "__main__":
    main()
