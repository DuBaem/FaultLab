"""Unit tests for FaultLab fault application and cleanup commands.

These tests use a fake Docker adapter. They do not require elevated privileges
and cannot alter the host network.
"""

from __future__ import annotations

import subprocess
import unittest

from faultlab.docker_cli import NetworkAttachment
from faultlab.fault_adapters import FaultExecutor


class FakeDocker:
    def __init__(self) -> None:
        self.exec_calls: list[tuple[str, list[str], bool]] = []
        self.kill_calls: list[tuple[str, str]] = []
        self.started: list[str] = []
        self.health_waits: list[str] = []
        self.disconnected: list[str] = []
        self.reconnected: list[NetworkAttachment] = []
        self.qdisc_output = "qdisc noqueue 0: root refcnt 2"

    def exec(self, service, arguments, *, check=True):
        self.exec_calls.append((service, list(arguments), check))
        output = self.qdisc_output if arguments[:3] == ["tc", "qdisc", "show"] else ""
        return subprocess.CompletedProcess(arguments, 0, output, "")

    def kill(self, service, signal):
        self.kill_calls.append((service, signal))

    def ensure_started(self, service):
        self.started.append(service)

    def wait_until_healthy(self, service):
        self.health_waits.append(service)

    def disconnect(self, service):
        self.disconnected.append(service)
        return NetworkAttachment("container-1", service, ("faultlab_default",))

    def reconnect(self, attachment):
        self.reconnected.append(attachment)


class FaultExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.docker = FakeDocker()
        self.executor = FaultExecutor(self.docker)

    def test_latency_uses_bounded_tc_argument_list(self) -> None:
        action = {
            "id": "delay-server",
            "type": "latency",
            "parameters": {"latency_ms": 250, "jitter_ms": 25},
        }
        handle = self.executor.apply(action, "server")

        self.assertEqual(
            (
                "server",
                [
                    "tc",
                    "qdisc",
                    "replace",
                    "dev",
                    "eth0",
                    "root",
                    "netem",
                    "delay",
                    "250ms",
                    "25ms",
                ],
                True,
            ),
            self.docker.exec_calls[0],
        )

        self.executor.cleanup(handle)
        self.assertIn(
            ("server", ["tc", "qdisc", "del", "dev", "eth0", "root"], False),
            self.docker.exec_calls,
        )
        self.assertTrue(handle.cleaned)

    def test_packet_loss_is_applied_as_netem_percentage(self) -> None:
        action = {
            "id": "drop-packets",
            "type": "packet_loss",
            "parameters": {"loss_percent": 12.5},
        }
        self.executor.apply(action, "server")

        self.assertEqual(
            [
                "tc",
                "qdisc",
                "replace",
                "dev",
                "eth0",
                "root",
                "netem",
                "loss",
                "12.5%",
            ],
            self.docker.exec_calls[0][1],
        )

    def test_disconnect_records_networks_for_reconnection(self) -> None:
        action = {
            "id": "isolate-server",
            "type": "disconnect",
            "parameters": {"direction": "both"},
        }
        handle = self.executor.apply(action, "server")
        self.executor.cleanup(handle)

        self.assertEqual(["server"], self.docker.disconnected)
        self.assertEqual([handle.cleanup_data], self.docker.reconnected)

    def test_process_failure_is_restarted_during_cleanup(self) -> None:
        action = {
            "id": "stop-server",
            "type": "process_failure",
            "parameters": {"signal": "SIGTERM"},
        }
        handle = self.executor.apply(action, "server")
        self.executor.cleanup(handle)

        self.assertEqual([("server", "SIGTERM")], self.docker.kill_calls)
        self.assertEqual(["server"], self.docker.started)
        self.assertEqual(["server"], self.docker.health_waits)

    def test_cleanup_is_idempotent(self) -> None:
        action = {
            "id": "stop-server",
            "type": "process_failure",
            "parameters": {"signal": "SIGTERM"},
        }
        handle = self.executor.apply(action, "server")
        self.executor.cleanup(handle)
        self.executor.cleanup(handle)

        self.assertEqual(["server"], self.docker.started)

    def test_network_cleanup_fails_if_netem_rule_remains(self) -> None:
        action = {
            "id": "delay-server",
            "type": "latency",
            "parameters": {"latency_ms": 100},
        }
        handle = self.executor.apply(action, "server")
        self.docker.qdisc_output = "qdisc netem 8001: root refcnt 2 limit 1000 delay 100ms"

        with self.assertRaisesRegex(RuntimeError, "could not be verified"):
            self.executor.cleanup(handle)


if __name__ == "__main__":
    unittest.main()
