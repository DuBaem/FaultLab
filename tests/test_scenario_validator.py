"""Unit tests for the dry-run FaultLab scenario validator.

AI-assistance disclosure: the initial tests were generated with OpenAI Codex on
October 4, 2026. Student review, extension, and documented execution are needed
before the tests are claimed as a course contribution.
"""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from faultlab.scenario_validator import validate_scenario


ROOT = Path(__file__).resolve().parents[1]


def load_example(name: str) -> dict:
    return json.loads((ROOT / "scenarios" / name).read_text(encoding="utf-8"))


class ScenarioValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.valid = load_example("valid-latency.json")

    def messages_for(self, document: dict) -> list[str]:
        return [str(issue) for issue in validate_scenario(document)]

    def test_valid_latency_scenario_is_accepted(self) -> None:
        self.assertEqual([], validate_scenario(self.valid))

    def test_all_live_fault_examples_are_accepted(self) -> None:
        for name in (
            "valid-packet-loss.json",
            "valid-disconnect.json",
            "valid-process-failure.json",
            "demo-latency-packet-loss.json",
        ):
            with self.subTest(name=name):
                self.assertEqual([], validate_scenario(load_example(name)))

    def test_unapproved_service_is_rejected(self) -> None:
        document = load_example("invalid-target.json")
        messages = self.messages_for(document)
        self.assertTrue(any("approved FaultLab 1.0 fault target" in message for message in messages))

    def test_action_must_reference_declared_target(self) -> None:
        document = copy.deepcopy(self.valid)
        document["actions"][0]["target"] = "missing-target"
        messages = self.messages_for(document)
        self.assertTrue(any("declared target" in message for message in messages))

    def test_latency_limit_is_enforced(self) -> None:
        document = copy.deepcopy(self.valid)
        document["actions"][0]["parameters"]["latency_ms"] = 5001
        messages = self.messages_for(document)
        self.assertTrue(any("between 1 and 5000" in message for message in messages))

    def test_action_cannot_exceed_scenario_duration(self) -> None:
        document = copy.deepcopy(self.valid)
        document["actions"][0]["start_after_seconds"] = 25
        document["actions"][0]["duration_seconds"] = 10
        messages = self.messages_for(document)
        self.assertTrue(any("exceeds" in message for message in messages))

    def test_duplicate_action_ids_are_rejected(self) -> None:
        document = copy.deepcopy(self.valid)
        document["actions"].append(copy.deepcopy(document["actions"][0]))
        messages = self.messages_for(document)
        self.assertTrue(any("must be unique" in message for message in messages))

    def test_cleanup_is_required(self) -> None:
        document = copy.deepcopy(self.valid)
        document["safety"]["cleanup_required"] = False
        messages = self.messages_for(document)
        self.assertTrue(any("must be true" in message for message in messages))

    def test_expected_outcome_is_required(self) -> None:
        document = copy.deepcopy(self.valid)
        document["expected_outcomes"] = []
        messages = self.messages_for(document)
        self.assertTrue(any("non-empty array" in message for message in messages))

    def test_unknown_command_field_is_rejected(self) -> None:
        document = copy.deepcopy(self.valid)
        document["actions"][0]["command"] = "tc qdisc replace ..."
        messages = self.messages_for(document)
        self.assertTrue(any("field is not allowed" in message for message in messages))

    def test_directional_disconnect_is_not_supported_in_version_one(self) -> None:
        document = load_example("valid-disconnect.json")
        document["actions"][0]["parameters"]["direction"] = "egress"
        messages = self.messages_for(document)
        self.assertTrue(any('must equal "both"' in message for message in messages))

    def test_process_restart_time_must_match_action_duration(self) -> None:
        document = load_example("valid-process-failure.json")
        document["actions"][0]["parameters"]["restart_after_seconds"] = 3
        messages = self.messages_for(document)
        self.assertTrue(any("must match duration_seconds" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
