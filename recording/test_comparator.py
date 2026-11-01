
import unittest
from recording.comparator import compare_runs
from datetime import datetime, timezone
from recording.comparator import compare_runs, analyze_phases


class TestComparator(unittest.TestCase):
    
    def test_compare_experiments_from_saved_files(self):
        import json
        import tempfile
        from pathlib import Path

        from recording.comparator import compare_experiments

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original_dir = root / "original"
            replay_dir = root / "replay"

            original_dir.mkdir()
            replay_dir.mkdir()

            def save_run(directory, run_id, during_latency, drift):
                summary = {
                    "run_id": run_id,
                    "scenario_id": "test-latency",
                    "started_at": "2026-11-01T12:00:00+00:00",
                    "actions": [
                        {
                            "observed_start_seconds": 2.0,
                            "observed_end_seconds": 5.0,
                            "start_drift_seconds": drift,
                        }
                    ],
                }

                observations = [
                    {
                        "request_id": "request-0000",
                        "started_at_utc": "2026-11-01T12:00:01+00:00",
                        "success": True,
                        "latency_ms": 20.0,
                    },
                    {
                        "request_id": "request-0001",
                        "started_at_utc": "2026-11-01T12:00:03+00:00",
                        "success": True,
                        "latency_ms": during_latency,
                    },
                    {
                        "request_id": "request-0002",
                        "started_at_utc": "2026-11-01T12:00:06+00:00",
                        "success": True,
                        "latency_ms": 15.0,
                    },
                ]

                (directory / "summary.json").write_text(
                    json.dumps(summary),
                    encoding="utf-8",
                )

                (directory / "observations.json").write_text(
                    json.dumps({
                        "run_id": run_id,
                        "request_count": len(observations),
                        "observations": observations,
                    }),
                    encoding="utf-8",
                )

            save_run(original_dir, "original-run", 500.0, 1.2)
            save_run(replay_dir, "replay-run", 510.0, 1.5)

            report = compare_experiments(
                original_dir,
                replay_dir,
            )

            self.assertEqual(
                report["outcome_comparison"]["outcome_match_rate"],
                100.0,
            )

            self.assertEqual(
                report["original_phases"]["during"]["median_latency_ms"],
                500.0,
            )

            self.assertEqual(
                report["replay_phases"]["during"]["median_latency_ms"],
                510.0,
            )

            self.assertEqual(
                report["during_fault_median_difference_pct"],
                2.0,
            )

            self.assertAlmostEqual(
                report["timing_comparison"]["start_drift_difference_seconds"],
                0.3,
            )

    
    def test_phase_analysis(self):
        summary = {
            "started_at": "2026-11-01T12:00:00+00:00",
            "actions": [
                {
                    "observed_start_seconds": 2.0,
                    "observed_end_seconds": 5.0,
                }
            ],
        }

        observations = [
            {
                "request_id": "before",
                "started_at_utc": "2026-11-01T12:00:01+00:00",
                "success": True,
                "latency_ms": 20.0,
            },
            {
                "request_id": "during",
                "started_at_utc": "2026-11-01T12:00:03+00:00",
                "success": True,
                "latency_ms": 520.0,
            },
            {
                "request_id": "after",
                "started_at_utc": "2026-11-01T12:00:06+00:00",
                "success": True,
                "latency_ms": 15.0,
            },
        ]

        phases = analyze_phases(summary, observations)

        self.assertEqual(phases["before"]["requests"], 1)
        self.assertEqual(phases["during"]["requests"], 1)
        self.assertEqual(phases["after"]["requests"], 1)

        self.assertEqual(
            phases["during"]["median_latency_ms"],
            520.0,
        )

        self.assertEqual(
            phases["after"]["median_latency_ms"],
            15.0,
        )


    def test_identical_outcomes(self):
        original = [
            {"request_id": "req-1", "success": True},
            {"request_id": "req-2", "success": False},
            {"request_id": "req-3", "success": True}
        ]

        replay = [
            {"request_id": "req-1", "success": True},
            {"request_id": "req-2", "success": False},
            {"request_id": "req-3", "success": True}
        ]

        result = compare_runs(original, replay)

        self.assertEqual(result["outcome_match_rate"], 100.0)
        self.assertEqual(result["matching_outcomes"], 3)
        self.assertEqual(result["original_failures"], 1)
        self.assertEqual(result["replay_failures"], 1)

    def test_different_outcomes(self):
        original = [
            {"request_id": "req-1", "success": True},
            {"request_id": "req-2", "success": False},
            {"request_id": "req-3", "success": False}
        ]

        replay = [
            {"request_id": "req-1", "success": True},
            {"request_id": "req-2", "success": True},
            {"request_id": "req-3", "success": False}
        ]

        result = compare_runs(original, replay)

        self.assertEqual(result["outcome_match_rate"], 66.67)
        self.assertEqual(result["matching_outcomes"], 2)
        self.assertEqual(result["original_failures"], 2)
        self.assertEqual(result["replay_failures"], 1)

    def test_unmatched_requests(self):
        original = [
            {"request_id": "req-1", "success": True},
            {"request_id": "req-2", "success": False}
        ]

        replay = [
            {"request_id": "req-1", "success": True},
            {"request_id": "req-3", "success": False}
        ]

        result = compare_runs(original, replay)

        self.assertEqual(result["compared_requests"], 1)
        self.assertEqual(result["unmatched_original_requests"], ["req-2"])
        self.assertEqual(result["unmatched_replay_requests"], ["req-3"])

    def test_no_common_requests(self):
        original = [
            {"request_id": "req-1", "success": True}
        ]

        replay = [
            {"request_id": "req-2", "success": False}
        ]

        result = compare_runs(original, replay)

        self.assertIsNone(result["outcome_match_rate"])
        self.assertEqual(result["compared_requests"], 0)


if __name__ == "__main__":
    unittest.main()
