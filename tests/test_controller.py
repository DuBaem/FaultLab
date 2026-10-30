"""Tests for timed scenario execution, event output, and emergency cleanup."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from faultlab.controller import ScenarioExecutionError, execute_scenario
from faultlab.fault_adapters import DryRunFaultExecutor
from faultlab.scenario_validator import ScenarioValidationError


ROOT = Path(__file__).resolve().parents[1]


def load_scenario(name: str) -> dict:
    return json.loads((ROOT / "scenarios" / name).read_text(encoding="utf-8"))


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class ScenarioControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.now = lambda: datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)

    def test_two_fault_demo_follows_planned_schedule_and_writes_bundle(self) -> None:
        scenario = load_scenario("demo-latency-packet-loss.json")
        executor = DryRunFaultExecutor()

        with tempfile.TemporaryDirectory(dir=ROOT / "results") as directory:
            summary = execute_scenario(
                scenario,
                executor=executor,
                results_dir=Path(directory),
                monotonic=self.clock.monotonic,
                sleep=self.clock.sleep,
                now=self.now,
            )
            run_dir = Path(directory) / summary["run_id"]
            events = [
                json.loads(line)
                for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
            ]

            self.assertEqual("passed", summary["status"])
            self.assertEqual(2, summary["actions_completed"])
            self.assertEqual(
                ["add-250ms-delay", "drop-25-percent"],
                [handle.action_id for handle in executor.applied],
            )
            self.assertEqual(2, len(executor.cleaned))
            self.assertTrue((run_dir / "scenario.json").exists())
            self.assertTrue((run_dir / "summary.json").exists())
            self.assertEqual(
                [1.0, 6.0],
                [action["observed_start_seconds"] for action in summary["actions"]],
            )
            self.assertIn("fault_applied", [event["event_type"] for event in events])
            self.assertIn("fault_cleaned", [event["event_type"] for event in events])

    def test_overlapping_actions_are_rejected_before_execution(self) -> None:
        scenario = load_scenario("demo-latency-packet-loss.json")
        scenario["actions"][1]["start_after_seconds"] = 2

        with tempfile.TemporaryDirectory(dir=ROOT / "results") as directory:
            with self.assertRaisesRegex(ScenarioValidationError, "overlaps"):
                execute_scenario(
                    scenario,
                    executor=DryRunFaultExecutor(),
                    results_dir=Path(directory),
                    monotonic=self.clock.monotonic,
                    sleep=self.clock.sleep,
                    now=self.now,
                )

    def test_interrupted_fault_is_cleaned_and_failure_is_documented(self) -> None:
        scenario = copy.deepcopy(load_scenario("valid-latency.json"))
        scenario["actions"][0]["start_after_seconds"] = 0
        executor = DryRunFaultExecutor()

        def interrupted_sleep(_seconds: float) -> None:
            raise RuntimeError("simulated interruption")

        with tempfile.TemporaryDirectory(dir=ROOT / "results") as directory:
            with self.assertRaises(ScenarioExecutionError) as raised:
                execute_scenario(
                    scenario,
                    executor=executor,
                    results_dir=Path(directory),
                    monotonic=self.clock.monotonic,
                    sleep=interrupted_sleep,
                    now=self.now,
                )

            summary = json.loads(raised.exception.summary_path.read_text(encoding="utf-8"))
            self.assertEqual("failed", summary["status"])
            self.assertEqual(1, len(executor.cleaned))
            self.assertTrue(executor.cleaned[0].cleaned)


if __name__ == "__main__":
    unittest.main()
