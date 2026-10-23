"""Small, allowlisted wrapper around the Docker command-line interface.

Scenario data never becomes a shell command. Every Docker and Linux argument is
passed as a separate subprocess argument after service names and values have
been validated.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from faultlab.scenario_validator import ALLOWED_SERVICES


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class DockerCommandError(RuntimeError):
    """Raised when an expected Docker command cannot be completed."""

    def __init__(self, command: Sequence[str], result: subprocess.CompletedProcess[str]):
        self.command = tuple(command)
        self.result = result
        detail = (result.stderr or result.stdout or "no output").strip()
        super().__init__(
            f"Docker command failed with status {result.returncode}: "
            f"{' '.join(command)}\n{detail}"
        )


@dataclass(frozen=True, slots=True)
class NetworkAttachment:
    """Information needed to reconnect a temporarily isolated service."""

    container_id: str
    service: str
    networks: tuple[str, ...]


class DockerCompose:
    """Execute a narrow set of Docker operations for the local FaultLab stack."""

    def __init__(
        self,
        project_root: Path | None = None,
        runner: CommandRunner = subprocess.run,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[1]
        self._runner = runner
        self._monotonic = monotonic
        self._sleep = sleep

    @staticmethod
    def _validate_service(service: str) -> None:
        if service not in ALLOWED_SERVICES:
            allowed = ", ".join(sorted(ALLOWED_SERVICES))
            raise ValueError(f"unsupported service {service!r}; expected one of: {allowed}")

    def _run(
        self,
        command: Sequence[str],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = self._runner(
                list(command),
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Docker could not be started. Install Docker Desktop and make sure "
                "the Docker engine is running."
            ) from exc

        if check and result.returncode != 0:
            raise DockerCommandError(command, result)
        return result

    def compose(
        self,
        arguments: Sequence[str],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self._run(["docker", "compose", *arguments], check=check)

    def docker(
        self,
        arguments: Sequence[str],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self._run(["docker", *arguments], check=check)

    def exec(
        self,
        service: str,
        arguments: Sequence[str],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        self._validate_service(service)
        return self.compose(["exec", "-T", service, *arguments], check=check)

    def kill(self, service: str, signal: str) -> None:
        self._validate_service(service)
        if signal not in {"SIGTERM", "SIGKILL"}:
            raise ValueError("signal must be SIGTERM or SIGKILL")
        self.compose(["kill", "-s", signal, service])

    def ensure_started(self, service: str) -> None:
        """Start a stopped service, creating it if the container was removed."""

        self._validate_service(service)
        result = self.compose(["start", service], check=False)
        if result.returncode != 0:
            self.compose(["up", "-d", "--no-deps", service])

    def wait_until_healthy(
        self,
        service: str,
        *,
        timeout_seconds: float = 30,
        poll_seconds: float = 0.5,
    ) -> None:
        """Wait until a restarted service reports healthy or running."""

        container_id = self.container_id(service)
        deadline = self._monotonic() + timeout_seconds
        template = "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}"
        last_status = "unknown"
        while self._monotonic() < deadline:
            result = self.docker(
                ["inspect", "--format", template, container_id], check=False
            )
            if result.returncode == 0:
                last_status = result.stdout.strip().lower()
                if last_status in {"healthy", "running"}:
                    return
                if last_status in {"dead", "removing"}:
                    break
            self._sleep(poll_seconds)
        raise RuntimeError(
            f"service {service!r} did not recover within {timeout_seconds:g} seconds "
            f"(last status: {last_status})"
        )

    def container_id(self, service: str) -> str:
        self._validate_service(service)
        result = self.compose(["ps", "-q", service])
        container_id = result.stdout.strip()
        if not container_id:
            raise RuntimeError(
                f"service {service!r} is not running; start the FaultLab stack first"
            )
        return container_id

    def disconnect(self, service: str) -> NetworkAttachment:
        """Disconnect a running service from each attached Docker network."""

        container_id = self.container_id(service)
        template = "{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{println}}{{end}}"
        result = self.docker(["inspect", "--format", template, container_id])
        networks = tuple(line.strip() for line in result.stdout.splitlines() if line.strip())
        if not networks:
            raise RuntimeError(f"service {service!r} has no attached Docker network")

        disconnected: list[str] = []
        try:
            for network in networks:
                self.docker(["network", "disconnect", network, container_id])
                disconnected.append(network)
        except Exception:
            for network in disconnected:
                self.docker(
                    ["network", "connect", "--alias", service, network, container_id],
                    check=False,
                )
            raise

        return NetworkAttachment(container_id, service, networks)

    def reconnect(self, attachment: NetworkAttachment) -> None:
        """Reconnect a service and restore its Compose service-name alias."""

        for network in attachment.networks:
            result = self.docker(
                [
                    "network",
                    "connect",
                    "--alias",
                    attachment.service,
                    network,
                    attachment.container_id,
                ],
                check=False,
            )
            detail = f"{result.stdout}\n{result.stderr}".lower()
            already_connected = "already exists" in detail or "already connected" in detail
            if result.returncode != 0 and not already_connected:
                raise DockerCommandError(
                    [
                        "docker",
                        "network",
                        "connect",
                        "--alias",
                        attachment.service,
                        network,
                        attachment.container_id,
                    ],
                    result,
                )
