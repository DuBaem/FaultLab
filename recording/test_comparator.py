
import unittest
from comparator import compare_runs


class TestComparator(unittest.TestCase):

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
