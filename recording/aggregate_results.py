
import argparse
import json
import statistics
from pathlib import Path

from recording.comparator import compare_experiments


def aggregate_experiments(pairs):
    if not pairs:
        raise ValueError("At least one experiment pair is required")

    trials = []

    for original_dir, replay_dir in pairs:
        comparison = compare_experiments(
            Path(original_dir),
            Path(replay_dir),
        )

        outcomes = comparison["outcome_comparison"]
        timing = comparison["timing_comparison"]

        original_count = outcomes["original_requests"]
        replay_count = outcomes["replay_requests"]
        compared_count = outcomes["compared_requests"]

        coverage = (
            100 * compared_count / max(original_count, replay_count)
            if max(original_count, replay_count) > 0
            else None
        )

        trials.append({
            "original_run_id": comparison["original_run_id"],
            "replay_run_id": comparison["replay_run_id"],
            "scenario_id": comparison["scenario_id"],
            "original_requests": original_count,
            "replay_requests": replay_count,
            "compared_requests": compared_count,
            "matching_outcomes": outcomes["matching_outcomes"],
            "outcome_match_rate": outcomes["outcome_match_rate"],
            "request_coverage_pct": (
                round(coverage, 2)
                if coverage is not None
                else None
            ),
            "during_fault_median_difference_pct":
                comparison["during_fault_median_difference_pct"],
            "start_drift_difference_seconds":
                timing["start_drift_difference_seconds"],
        })

    total_original = sum(
        trial["original_requests"] for trial in trials
    )
    total_replay = sum(
        trial["replay_requests"] for trial in trials
    )
    total_compared = sum(
        trial["compared_requests"] for trial in trials
    )
    total_matching = sum(
        trial["matching_outcomes"] for trial in trials
    )

    latency_differences = [
        abs(trial["during_fault_median_difference_pct"])
        for trial in trials
        if trial["during_fault_median_difference_pct"] is not None
    ]

    start_differences = [
        abs(trial["start_drift_difference_seconds"])
        for trial in trials
        if trial["start_drift_difference_seconds"] is not None
    ]

    return {
        "trial_count": len(trials),
        "summary": {
            "total_original_requests": total_original,
            "total_replay_requests": total_replay,
            "total_compared_requests": total_compared,
            "total_matching_outcomes": total_matching,
            "overall_outcome_agreement_pct": (
                round(100 * total_matching / total_compared, 2)
                if total_compared
                else None
            ),
            "overall_request_coverage_pct": (
                round(
                    100 * total_compared
                    / max(total_original, total_replay),
                    2,
                )
                if max(total_original, total_replay)
                else None
            ),
            "mean_absolute_fault_latency_difference_pct": (
                round(statistics.mean(latency_differences), 2)
                if latency_differences
                else None
            ),
            "min_absolute_fault_latency_difference_pct": (
                round(min(latency_differences), 2)
                if latency_differences
                else None
            ),
            "max_absolute_fault_latency_difference_pct": (
                round(max(latency_differences), 2)
                if latency_differences
                else None
            ),
            "mean_absolute_start_drift_difference_seconds": (
                round(statistics.mean(start_differences), 4)
                if start_differences
                else None
            ),
        },
        "trials": trials,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Aggregate FaultLab original/replay comparisons"
    )

    parser.add_argument(
        "pairs",
        nargs="+",
        help="Experiment directories in original/replay pairs",
    )

    parser.add_argument(
        "--output",
        help="Optional path to save the aggregate JSON report",
    )

    args = parser.parse_args()

    if len(args.pairs) % 2 != 0:
        parser.error(
            "Provide an even number of directories: "
            "original replay [original replay ...]"
        )

    pairs = [
        (args.pairs[i], args.pairs[i + 1])
        for i in range(0, len(args.pairs), 2)
    ]

    report = aggregate_experiments(pairs)

    output = json.dumps(report, indent=2)
    print(output)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        output_path.write_text(
            output + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()

