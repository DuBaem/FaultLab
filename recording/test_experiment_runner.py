
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from recording.experiment_runner import run_experiment


class TestExperimentRunner(unittest.TestCase):

    
    def test_fixed_observation_duration(self):
        import json
        import tempfile
        import time
        from pathlib import Path
        from unittest.mock import patch

        from recording.experiment_runner import run_experiment

        with tempfile.TemporaryDirectory() as temp:
            results_dir = Path(temp)

            def fake_request(*args, **kwargs):
                return {
                    "request_id": args[1],
                    "success": True,
                    "latency_ms": 1.0,
                }

            def fake_controller(scenario, *, results_dir, **kwargs):
                run_dir = Path(results_dir) / "fixed-window-test"
                run_dir.mkdir(parents=True, exist_ok=True)

                return {
                    "run_id": "fixed-window-test",
                    "status": "passed",
                }

            with (
                patch(
                    "recording.experiment_runner.run_request",
                    side_effect=fake_request,
                ),
                patch(
                    "recording.experiment_runner.execute_scenario",
                    side_effect=fake_controller,
                ),
            ):
                started = time.perf_counter()

                result = run_experiment(
                    scenario={},
                    server_url="http://localhost:5000",
                    request_count=100,
                    request_interval=0.01,
                    request_timeout=1.0,
                    recovery_seconds=0,
                    observation_duration=0.1,
                    results_dir=results_dir,
                    dry_run=True,
                )

                elapsed = time.perf_counter() - started

            self.assertGreaterEqual(elapsed, 0.09)
            self.assertLess(elapsed, 1.0)

            self.assertGreater(result["request_count"], 0)
            self.assertLess(result["request_count"], 100)

            config = json.loads(
                Path(result["workload_config_path"]).read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(
                config["observation_duration"],
                0.1,
            )


    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.results_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_invalid_request_count(self):
        with self.assertRaises(ValueError):
            run_experiment(
                {},
                "http://localhost:5000",
                request_count=0,
                results_dir=self.results_dir,
                dry_run=True,
            )

    def test_invalid_timeout(self):
        with self.assertRaises(ValueError):
            run_experiment(
                {},
                "http://localhost:5000",
                request_timeout=0,
                results_dir=self.results_dir,
                dry_run=True,
            )

    @patch("recording.experiment_runner.execute_scenario")
    @patch("recording.experiment_runner.run_request")
    def test_concurrent_execution_and_observations(
        self, mock_request, mock_controller
    ):
        request_started = threading.Event()

        def fake_request(server_url, request_id, value, timeout_s):
            request_started.set()
            return {
                "request_id": request_id,
                "success": True,
                "latency_ms": 10.0,
                "error": None,
            }

        def fake_controller(scenario, **kwargs):
            if not request_started.wait(timeout=2):
                raise AssertionError(
                    "Workload did not start while controller was running"
                )

            time.sleep(0.05)

            return {
                "run_id": "test-run-001",
                "status": "passed",
            }

        mock_request.side_effect = fake_request
        mock_controller.side_effect = fake_controller

        result = run_experiment(
            {"scenario_id": "test-scenario"},
            "http://localhost:5000",
            request_count=5,
            request_interval=0.01,
            results_dir=self.results_dir,
            dry_run=True,
        )

        observation_file = (
            self.results_dir / "test-run-001" / "observations.json"
        )

        self.assertTrue(observation_file.exists())

        config_file = (
            self.results_dir / "test-run-001" / "workload_config.json"
        )

        self.assertTrue(config_file.exists())

        config = json.loads(config_file.read_text(encoding="utf-8"))

        self.assertEqual(config["request_count"], 5)
        self.assertEqual(config["request_interval"], 0.01)
        self.assertEqual(config["server_url"], "http://localhost:5000")

        data = json.loads(
            observation_file.read_text(encoding="utf-8")
        )

        self.assertGreater(data["request_count"], 0)
        self.assertEqual(
            data["request_count"],
            result["request_count"],
        )
        self.assertEqual(data["run_id"], "test-run-001")
        self.assertEqual(result["workload_errors"], [])

        mock_controller.assert_called_once()


    @patch("recording.experiment_runner.execute_scenario")
    @patch("recording.experiment_runner.run_request")
    def test_requests_continue_after_controller_finishes(
        self, mock_request, mock_controller
    ):
        controller_finished = threading.Event()

        def fake_request(server_url, request_id, value, timeout_s):
            return {
                "request_id": request_id,
                "success": True,
                "latency_ms": 5.0,
                "error": None,
            }

        def fake_controller(scenario, **kwargs):
            controller_finished.set()
            return {
                "run_id": "recovery-test",
                "status": "passed",
            }

        mock_request.side_effect = fake_request
        mock_controller.side_effect = fake_controller

        result = run_experiment(
            {"scenario_id": "recovery-test"},
            "http://localhost:5000",
            request_count=5,
            request_interval=0.02,
            recovery_seconds=0.5,
            results_dir=self.results_dir,
            dry_run=True,
        )

        self.assertTrue(controller_finished.is_set())
        self.assertEqual(result["request_count"], 5)

        observations = json.loads(
            (
                self.results_dir
                / "recovery-test"
                / "observations.json"
            ).read_text(encoding="utf-8")
        )["observations"]

        self.assertEqual(len(observations), 5)
        self.assertTrue(
            all(
                "elapsed_since_start_s" in item
                for item in observations
            )
        )

if __name__ == "__main__":
    unittest.main()
