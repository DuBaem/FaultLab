
import json
import tempfile
import unittest
from pathlib import Path

from recording.replay import replay_experiment


class TestReplay(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.original_dir = self.root / "original-run"
        self.original_dir.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_missing_scenario(self):
        (self.original_dir / "summary.json").write_text(
            json.dumps({
                "run_id": "original-run",
                "scenario_id": "test-scenario",
                "status": "passed"
            }),
            encoding="utf-8"
        )

        with self.assertRaises(FileNotFoundError):
            replay_experiment(
                self.original_dir,
                results_dir=self.root / "replays",
                dry_run=True
            )

    def test_failed_original_run(self):
        (self.original_dir / "scenario.json").write_text(
            json.dumps({"scenario_id": "test-scenario"}),
            encoding="utf-8"
        )

        (self.original_dir / "summary.json").write_text(
            json.dumps({
                "run_id": "original-run",
                "scenario_id": "test-scenario",
                "status": "failed"
            }),
            encoding="utf-8"
        )

        with self.assertRaises(ValueError):
            replay_experiment(
                self.original_dir,
                results_dir=self.root / "replays",
                dry_run=True
            )

    def test_successful_replay(self):
        # Use the repository's validated example scenario.
        example = Path("scenarios/valid-latency.json")
        scenario = json.loads(
            example.read_text(encoding="utf-8")
        )

        (self.original_dir / "scenario.json").write_text(
            json.dumps(scenario),
            encoding="utf-8"
        )

        (self.original_dir / "summary.json").write_text(
            json.dumps({
                "run_id": "original-run",
                "scenario_id": scenario["scenario_id"],
                "status": "passed"
            }),
            encoding="utf-8"
        )

        summary = replay_experiment(
            self.original_dir,
            results_dir=self.root / "replays",
            dry_run=True
        )

        replay_dir = (
            self.root / "replays" / summary["run_id"]
        )

        self.assertEqual(summary["status"], "passed")
        self.assertTrue(
            (replay_dir / "replay_metadata.json").exists()
        )

        metadata = json.loads(
            (replay_dir / "replay_metadata.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            metadata["original_run_id"],
            "original-run"
        )
        self.assertEqual(
            metadata["replay_run_id"],
            summary["run_id"]
        )


if __name__ == "__main__":
    unittest.main()
