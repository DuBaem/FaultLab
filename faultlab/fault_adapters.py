"""Bounded Docker adapters for FaultLab's four approved fault categories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from faultlab.docker_cli import DockerCompose, NetworkAttachment


NETWORK_FAULT_TYPES = frozenset({"latency", "packet_loss"})


def _format_number(value: int | float) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.3f}".rstrip("0").rstrip(".")


@dataclass(slots=True)
class FaultHandle:
    """Runtime state required to reverse one applied fault."""

    action_id: str
    fault_type: str
    service: str
    cleanup_data: Any = None
    cleaned: bool = False


class FaultExecutor:
    """Apply and reverse validated faults inside the local Docker environment."""

    def __init__(self, docker: DockerCompose | None = None) -> None:
        self.docker = docker or DockerCompose()

    def apply(self, action: Mapping[str, Any], service: str) -> FaultHandle:
        fault_type = str(action["type"])
        action_id = str(action["id"])
        parameters = action["parameters"]

        if fault_type == "latency":
            latency = _format_number(parameters["latency_ms"])
            command = [
                "tc",
                "qdisc",
                "replace",
                "dev",
                "eth0",
                "root",
                "netem",
                "delay",
                f"{latency}ms",
            ]
            jitter = parameters.get("jitter_ms", 0)
            if float(jitter) > 0:
                command.append(f"{_format_number(jitter)}ms")
            self.docker.exec(service, command)

        elif fault_type == "packet_loss":
            loss = _format_number(parameters["loss_percent"])
            self.docker.exec(
                service,
                ["tc", "qdisc", "replace", "dev", "eth0", "root", "netem", "loss", f"{loss}%"],
            )

        elif fault_type == "disconnect":
            if parameters["direction"] != "both":
                raise ValueError("FaultLab 1.0 supports full service disconnection only")
            attachment = self.docker.disconnect(service)
            return FaultHandle(action_id, fault_type, service, attachment)

        elif fault_type == "process_failure":
            self.docker.kill(service, parameters["signal"])

        else:
            raise ValueError(f"unsupported fault type: {fault_type}")

        return FaultHandle(action_id, fault_type, service)

    def cleanup(self, handle: FaultHandle) -> None:
        """Reverse one fault. Calling cleanup twice is harmless."""

        if handle.cleaned:
            return

        if handle.fault_type in NETWORK_FAULT_TYPES:
            self.docker.exec(
                handle.service,
                ["tc", "qdisc", "del", "dev", "eth0", "root"],
                check=False,
            )
            remaining = self.docker.exec(
                handle.service,
                ["tc", "qdisc", "show", "dev", "eth0"],
                check=False,
            )
            if remaining.returncode != 0 or "netem" in remaining.stdout.lower():
                raise RuntimeError(
                    f"netem cleanup could not be verified for service {handle.service!r}"
                )

        elif handle.fault_type == "disconnect":
            if not isinstance(handle.cleanup_data, NetworkAttachment):
                raise RuntimeError("disconnect fault is missing its network attachment data")
            self.docker.reconnect(handle.cleanup_data)

        elif handle.fault_type == "process_failure":
            self.docker.ensure_started(handle.service)
            self.docker.wait_until_healthy(handle.service)

        else:
            raise ValueError(f"unsupported fault type: {handle.fault_type}")

        handle.cleaned = True


class DryRunFaultExecutor:
    """Test double that records actions without changing Docker state."""

    def __init__(self) -> None:
        self.applied: list[FaultHandle] = []
        self.cleaned: list[FaultHandle] = []

    def apply(self, action: Mapping[str, Any], service: str) -> FaultHandle:
        handle = FaultHandle(str(action["id"]), str(action["type"]), service)
        self.applied.append(handle)
        return handle

    def cleanup(self, handle: FaultHandle) -> None:
        if not handle.cleaned:
            handle.cleaned = True
            self.cleaned.append(handle)
