"""Tests that Docker operations use explicit arguments and allowlisted services."""

from __future__ import annotations

import subprocess
import unittest
from collections import deque
from pathlib import Path

from faultlab.docker_cli import DockerCompose, NetworkAttachment


class RecordingRunner:
    def __init__(self, responses=None) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.responses = deque(responses or [])

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), kwargs))
        if self.responses:
            return self.responses.popleft()
        return subprocess.CompletedProcess(command, 0, "", "")


class DockerComposeTests(unittest.TestCase):
    def test_exec_passes_arguments_without_a_shell(self) -> None:
        runner = RecordingRunner()
        docker = DockerCompose(Path("C:/FaultLab"), runner)

        docker.exec("server", ["tc", "qdisc", "show"])

        command, options = runner.calls[0]
        self.assertEqual(
            ["docker", "compose", "exec", "-T", "server", "tc", "qdisc", "show"],
            command,
        )
        self.assertNotIn("shell", options)

    def test_unapproved_service_is_rejected_before_subprocess(self) -> None:
        runner = RecordingRunner()
        docker = DockerCompose(Path("C:/FaultLab"), runner)

        with self.assertRaisesRegex(ValueError, "unsupported service"):
            docker.exec("database", ["echo", "no"])
        self.assertEqual([], runner.calls)

    def test_disconnect_collects_and_reconnects_attached_networks(self) -> None:
        runner = RecordingRunner(
            [
                subprocess.CompletedProcess([], 0, "container-123\n", ""),
                subprocess.CompletedProcess([], 0, "faultlab_default\nmetrics\n", ""),
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 0, "", ""),
            ]
        )
        docker = DockerCompose(Path("C:/FaultLab"), runner)

        attachment = docker.disconnect("server")
        docker.reconnect(attachment)

        commands = [call[0] for call in runner.calls]
        self.assertEqual(("faultlab_default", "metrics"), attachment.networks)
        self.assertIn(
            ["docker", "network", "disconnect", "faultlab_default", "container-123"],
            commands,
        )
        self.assertIn(
            [
                "docker",
                "network",
                "connect",
                "--alias",
                "server",
                "metrics",
                "container-123",
            ],
            commands,
        )

    def test_start_falls_back_to_compose_up_when_container_is_missing(self) -> None:
        runner = RecordingRunner(
            [
                subprocess.CompletedProcess([], 1, "", "missing"),
                subprocess.CompletedProcess([], 0, "", ""),
            ]
        )
        docker = DockerCompose(Path("C:/FaultLab"), runner)

        docker.ensure_started("server")

        self.assertEqual(
            ["docker", "compose", "up", "-d", "--no-deps", "server"],
            runner.calls[1][0],
        )

    def test_commands_have_a_timeout_and_report_timeouts_clearly(self) -> None:
        def stalled(command, **kwargs):
            self.assertEqual(30, kwargs["timeout"])
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        with self.assertRaisesRegex(RuntimeError, "timed out"):
            DockerCompose(runner=stalled).exec("server", ["tc", "qdisc", "show"])

    def test_invalid_command_timeouts_are_rejected(self) -> None:
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    DockerCompose(command_timeout_seconds=timeout)

    def test_interrupted_disconnect_restores_every_original_network(self) -> None:
        calls = []

        def interrupted(command, **kwargs):
            calls.append(command)
            if "ps" in command:
                return subprocess.CompletedProcess(command, 0, "container-1", "")
            if "inspect" in command:
                return subprocess.CompletedProcess(command, 0, "first\nsecond\n", "")
            if command[1:4] == ["network", "disconnect", "second"]:
                raise KeyboardInterrupt()
            return subprocess.CompletedProcess(command, 0, "", "")

        with self.assertRaises(KeyboardInterrupt):
            DockerCompose(runner=interrupted).disconnect("server")
        for network in ("first", "second"):
            self.assertIn(["docker", "network", "connect", "--alias", "server",
                           network, "container-1"], calls)

    def test_reconnect_attempts_other_networks_after_one_fails(self) -> None:
        runner = RecordingRunner([
            subprocess.CompletedProcess([], 1, "", "network unavailable"),
            subprocess.CompletedProcess([], 0, "", ""),
        ])
        with self.assertRaisesRegex(RuntimeError, "network unavailable"):
            DockerCompose(runner=runner).reconnect(
                NetworkAttachment("container-1", "server", ("first", "second")))
        self.assertEqual(2, len(runner.calls))


if __name__ == "__main__":
    unittest.main()
