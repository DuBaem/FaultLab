
import json
import tempfile
import unittest
from pathlib import Path

from observation_logger import save_observations


class TestObservationLogger(unittest.TestCase):

    def test_saves_observations(self):
        sample_requests = [
            {
                "request_id": "baseline-0001",
                "input_value": 10,
                "expected_result": 20,
                "observed_result": 20,
                "http_status": 200,
                "success": True,
                "latency_ms": 15.4,
                "error": None
            },
            {
                "request_id": "baseline-0002",
                "input_value": 10,
                "expected_result": 20,
                "observed_result": None,
                "http_status": None,
                "success": False,
                "latency_ms": None,
                "error": "Request timed out"
            }
        ]

        with tempfile.TemporaryDirectory() as folder:
            run_dir = Path(folder) / "test-run-001"

            output_path = save_observations(
                run_dir,
                sample_requests
            )

            self.assertTrue(output_path.exists())

            data = json.loads(
                output_path.read_text(encoding="utf-8")
            )

            self.assertEqual(data["run_id"], "test-run-001")
            self.assertEqual(data["request_count"], 2)
            self.assertEqual(len(data["observations"]), 2)
            self.assertTrue(data["observations"][0]["success"])
            self.assertFalse(data["observations"][1]["success"])


if __name__ == "__main__":
    unittest.main()
