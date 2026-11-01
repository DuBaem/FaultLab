
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    
    def test_replay_with_saved_workload(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from recording.replay import replay_experiment

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original_dir = root / "original"
            results_dir = root / "results"
            original_dir.mkdir()

            scenario = {
                "schema_version": "1.0",
                "scenario_id": "server-latency-demo",
                "description": "Replay test",
                "targets": [
                    {"name": "api-server", "service": "server"}
                ],
                "actions": [
                    {
                        "id": "delay-server",
                        "type": "latency",
                        "target": "api-server",
                        "start_after_seconds": 2,
                        "duration_seconds": 8,
                        "parameters": {
                            "latency_ms": 250,
                            "jitter_ms": 25
                        }
                    }
                ],
                "expected_outcomes": [
                    "Requests experience increased latency."
                ],
                "safety": {
                    "scope": "local_docker_only",
                    "cleanup_required": True,
                    "max_total_duration_seconds": 30
                }
            }

            (original_dir / "scenario.json").write_text(
                json.dumps(scenario),
                encoding="utf-8",
            )

            (original_dir / "summary.json").write_text(
                json.dumps({
                    "run_id": "original-run",
                    "scenario_id": "server-latency-demo",
                    "status": "passed",
                }),
                encoding="utf-8",
            )

            (original_dir / "workload_config.json").write_text(
                json.dumps({
                    "server_url": "http://localhost:5000",
                    "request_count": 100,
                    "request_interval": 0.2,
                    "request_timeout": 3.0,
                    "recovery_seconds": 4.0,
                    "input_value": 10,
                }),
                encoding="utf-8",
            )

            replay_dir = results_dir / "replay-run"

            def fake_run_experiment(**kwargs):
                replay_dir.mkdir(parents=True)
                return {
                    "summary": {
                        "run_id": "replay-run",
                        "scenario_id": "server-latency-demo",
                        "status": "passed",
                    },
                    "observation_path": str(
                        replay_dir / "observations.json"
                    ),
                    "workload_config_path": str(
                        replay_dir / "workload_config.json"
                    ),
                    "request_count": 42,
                    "workload_errors": [],
                }

            with patch(
                "recording.replay.run_experiment",
                side_effect=fake_run_experiment,
            ) as mocked_runner:
                summary = replay_experiment(
                    original_dir,
                    results_dir=results_dir,
                    dry_run=True,
                )

            self.assertEqual(summary["run_id"], "replay-run")

            mocked_runner.assert_called_once()

            kwargs = mocked_runner.call_args.kwargs
            self.assertEqual(kwargs["request_count"], 100)
            self.assertEqual(kwargs["request_interval"], 0.2)
            self.assertTrue(kwargs["dry_run"])

            metadata = json.loads(
                (replay_dir / "replay_metadata.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(
                metadata["original_run_id"],
                "original-run",
            )
            self.assertTrue(metadata["workload_replayed"])


if __name__ == "__main__":
    unittest.main()
