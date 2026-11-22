"""Coordinate local experiments and check the demo server after each fault."""

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from baseline.baseline import run_request
from faultlab.docker_cli import DockerCompose
from faultlab.fault_adapters import FaultExecutor, NETWORK_FAULT_TYPES

LOCAL_URL = "http://127.0.0.1:5000"


@contextmanager
def stack_lock():
    # The OS releases the lock on exit, including after an unexpected process exit.
    path = Path(tempfile.gettempdir()) / "faultlab-local-compose.lock"
    with path.open("a+b") as stream:
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another FaultLab run or reset is using this stack.") from exc
        yield


class CheckedExecutor(FaultExecutor):
    """Pin the current Compose server and verify its recovery between actions."""

    def __init__(self, docker=None):
        super().__init__(docker or DockerCompose())
        ensure_local_engine(self.docker)
        self.server_id = self.docker.bind_server()
        self.expected_networks = self.networks()
        if not self.expected_networks:
            raise RuntimeError("The FaultLab server needs its Compose network.")
        self.verify()

    def networks(self):
        data = self.docker.docker(["inspect", "--format", "{{json .NetworkSettings.Networks}}", self.server_id])
        return {name: (details["NetworkID"], "server" in (details.get("Aliases") or []))
                for name, details in json.loads(data.stdout).items()}

    def verify(self, *, queue_checked=False):
        if self.networks() != self.expected_networks:
            raise RuntimeError("The server's Docker networks changed. Run reset.py.")
        if not queue_checked:
            queue = self.docker.exec("server", ["tc", "qdisc", "show", "dev", "eth0"])
            if "netem" in queue.stdout.lower():
                raise RuntimeError("A netem rule is still active. Run reset.py.")
        probe = run_request(LOCAL_URL, "recovery-check", 10, 1)
        if not probe["success"]:
            raise RuntimeError(f"The recovery request failed: {probe['error']}. Run reset.py.")

    def cleanup(self, handle):
        super().cleanup(handle)
        # Network adapters already inspect the queue before returning.
        self.verify(queue_checked=handle.fault_type in NETWORK_FAULT_TYPES)


def ensure_local_engine(docker):
    host = os.environ.get("DOCKER_HOST")
    if not host or os.environ.get("DOCKER_CONTEXT"):
        host = docker.docker(["context", "inspect", "--format", "{{.Endpoints.docker.Host}}"]).stdout.strip()
    if not host.startswith(("unix:///", "npipe:////./pipe/")):
        raise RuntimeError("Select a local Docker Desktop or Unix socket context for this experiment.")
