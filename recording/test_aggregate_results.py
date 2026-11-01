
import unittest
from unittest.mock import patch

from recording.aggregate_results import aggregate_experiments


class TestAggregateResults(unittest.TestCase):

    @patch("recording.aggregate_results.compare_experiments")
    def test_aggregate_two_pairs(self, mock_compare):
        def comparison(original, replay, matched, latency, drift):
            return {
                "original_run_id": "original",
                "replay_run_id": "replay",
                "scenario_id": "server-latency-demo",
                "outcome_comparison": {
                    "original_requests": original,
                    "replay_requests": replay,
                    "compared_requests": matched,
                    "matching_outcomes": matched,
                    "outcome_match_rate": 100.0,
                },
                "timing_comparison": {
                    "start_drift_difference_seconds": drift,
                },
                "during_fault_median_difference_pct": latency,
            }

        mock_compare.side_effect = [
            comparison(47, 37, 37, 0.76, 0.4686),
            comparison(57, 61, 57, 2.94, -0.1053),
        ]

        report = aggregate_experiments([
            ("original-1", "replay-1"),
            ("original-2", "replay-2"),
        ])

        summary = report["summary"]

        self.assertEqual(report["trial_count"], 2)
        self.assertEqual(summary["total_original_requests"], 104)
        self.assertEqual(summary["total_replay_requests"], 98)
        self.assertEqual(summary["total_compared_requests"], 94)
        self.assertEqual(summary["total_matching_outcomes"], 94)
        self.assertEqual(summary["overall_outcome_agreement_pct"], 100.0)
        self.assertEqual(
            summary["overall_request_coverage_pct"],
            90.38,
        )
        self.assertEqual(
            summary["mean_absolute_fault_latency_difference_pct"],
            1.85,
        )
        self.assertEqual(
            summary["mean_absolute_start_drift_difference_seconds"],
            0.287,
        )

    def test_empty_pairs_rejected(self):
        with self.assertRaises(ValueError):
            aggregate_experiments([])


if __name__ == "__main__":
    unittest.main()
