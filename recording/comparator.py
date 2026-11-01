
import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path


def compare_runs(original, replay):
    """
    Compare application request outcomes between
    an original experiment and its replay.
    """

    original_by_id = {
        request["request_id"]: request
        for request in original
    }

    replay_by_id = {
        request["request_id"]: request
        for request in replay
    }

    common_ids = original_by_id.keys() & replay_by_id.keys()

    matching_outcomes = 0

    for request_id in common_ids:
        original_success = original_by_id[request_id]["success"]
        replay_success = replay_by_id[request_id]["success"]

        if original_success == replay_success:
            matching_outcomes += 1

    total = len(common_ids)

    return {
        "original_requests": len(original),
        "replay_requests": len(replay),
        "compared_requests": total,
        "original_failures": sum(
            not request["success"] for request in original
        ),
        "replay_failures": sum(
            not request["success"] for request in replay
        ),
        "matching_outcomes": matching_outcomes,
        "outcome_match_rate": (
            round(matching_outcomes / total * 100, 2)
            if total else None
        ),
        "unmatched_original_requests": sorted(
            original_by_id.keys() - replay_by_id.keys()
        ),
        "unmatched_replay_requests": sorted(
            replay_by_id.keys() - original_by_id.keys()
        ),
    }


def load_experiment(run_dir):
    """Load an experiment's summary and observations."""

    run_dir = Path(run_dir)

    summary = json.loads(
        (run_dir / "summary.json").read_text(encoding="utf-8")
    )

    observation_data = json.loads(
        (run_dir / "observations.json").read_text(
            encoding="utf-8"
        )
    )

    if summary["run_id"] != observation_data["run_id"]:
        raise ValueError(
            "Summary and observation run IDs do not match."
        )

    return summary, observation_data["observations"]


def analyze_phases(summary, observations):
    """
    Group requests by approximate fault timing.

    Uses controller start time and observed action offsets.
    Requests overlapping fault transitions are not
    separately classified.
    """

    actions = summary.get("actions", [])

    if len(actions) != 1:
        raise ValueError(
            "Phase analysis currently supports exactly one fault action."
        )

    action = actions[0]

    controller_start = datetime.fromisoformat(
        summary["started_at"]
    )

    fault_start = controller_start + timedelta(
        seconds=action["observed_start_seconds"]
    )

    fault_end = controller_start + timedelta(
        seconds=action["observed_end_seconds"]
    )

    phases = {
        "before": [],
        "during": [],
        "after": [],
    }

    for observation in observations:
        request_start = datetime.fromisoformat(
            observation["started_at_utc"]
        )

        if request_start < fault_start:
            phase = "before"
        elif request_start < fault_end:
            phase = "during"
        else:
            phase = "after"

        phases[phase].append(observation)

    results = {}

    for phase, requests in phases.items():
        latencies = [
            request["latency_ms"]
            for request in requests
            if request.get("latency_ms") is not None
        ]

        results[phase] = {
            "requests": len(requests),
            "successes": sum(
                bool(request["success"])
                for request in requests
            ),
            "failures": sum(
                not request["success"]
                for request in requests
            ),
            "median_latency_ms": (
                round(statistics.median(latencies), 2)
                if latencies else None
            ),
            "mean_latency_ms": (
                round(statistics.mean(latencies), 2)
                if latencies else None
            ),
        }

    return results


def compare_experiments(original_dir, replay_dir):
    """
    Compare two saved experiment directories,
    including outcomes, phase latency, and timing.
    """

    original_summary, original_observations = load_experiment(
        original_dir
    )

    replay_summary, replay_observations = load_experiment(
        replay_dir
    )

    if original_summary["scenario_id"] != replay_summary["scenario_id"]:
        raise ValueError(
            "Cannot compare experiments with different scenario IDs."
        )

    outcome_comparison = compare_runs(
        original_observations,
        replay_observations,
    )

    original_phases = analyze_phases(
        original_summary,
        original_observations,
    )

    replay_phases = analyze_phases(
        replay_summary,
        replay_observations,
    )

    original_action = original_summary["actions"][0]
    replay_action = replay_summary["actions"][0]

    original_fault_median = original_phases["during"][
        "median_latency_ms"
    ]

    replay_fault_median = replay_phases["during"][
        "median_latency_ms"
    ]

    latency_difference_pct = None

    if (
        original_fault_median is not None
        and replay_fault_median is not None
        and original_fault_median != 0
    ):
        latency_difference_pct = round(
            abs(replay_fault_median - original_fault_median)
            / original_fault_median
            * 100,
            2,
        )

    return {
        "original_run_id": original_summary["run_id"],
        "replay_run_id": replay_summary["run_id"],
        "scenario_id": original_summary["scenario_id"],
        "outcome_comparison": outcome_comparison,
        "original_phases": original_phases,
        "replay_phases": replay_phases,
        "timing_comparison": {
            "original_start_drift_seconds": original_action[
                "start_drift_seconds"
            ],
            "replay_start_drift_seconds": replay_action[
                "start_drift_seconds"
            ],
            "start_drift_difference_seconds": round(
                replay_action["start_drift_seconds"]
                - original_action["start_drift_seconds"],
                4,
            ),
        },
        "during_fault_median_difference_pct": latency_difference_pct,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Compare two recorded FaultLab experiments."
    )

    parser.add_argument("original_dir", type=Path)
    parser.add_argument("replay_dir", type=Path)

    args = parser.parse_args()

    report = compare_experiments(
        args.original_dir,
        args.replay_dir,
    )

    print(json.dumps(report, indent=2))
