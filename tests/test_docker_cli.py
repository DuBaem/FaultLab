"""Tests that Docker operations use explicit arguments and allowlisted services."""

from __future__ import annotations

import subprocess
import unittest
from collections import deque
from pathlib import Path

from faultlab.docker_cli import DockerCompose


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


if __name__ == "__main__":
    unittest.main()
