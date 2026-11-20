"""A trial should fail if a request misses the fault window or the server fails to recover."""
import copy

import pytest

import json
from types import SimpleNamespace

from faultlab.safety_check import evaluate_trial, probe_address


def batch(success=True, latency=10):
    return {"results": [{"success": success, "latency_ms": latency,
                         "started_at": "2026-11-20T12:00:01+00:00",
                         "finished_at": "2026-11-20T12:00:02+00:00"}],
            "summary": {"latency_ms": {"mean": latency if success else None}}}


WINDOW = ("2026-11-20T12:00:00+00:00", "2026-11-20T12:00:05+00:00")
RUN = {"status": "passed", "actions": [{"cleanup_verified": True}]}


@pytest.mark.parametrize("fault", ["packet_loss", "disconnect", "process_failure"])
def test_outage_requires_observed_failure_and_successful_recovery(fault):
    assert evaluate_trial(fault, batch(), batch(False), batch(), RUN, WINDOW, True)["passed"]
    assert not evaluate_trial(fault, batch(), batch(), batch(), RUN, WINDOW, True)["passed"]
    assert not evaluate_trial(fault, batch(), batch(False), batch(False), RUN, WINDOW, True)["passed"]


def test_latency_requires_a_measured_increase():
    assert evaluate_trial("latency", batch(), batch(latency=300), batch(), RUN, WINDOW, True)["passed"]
    assert not evaluate_trial("latency", batch(), batch(), batch(), RUN, WINDOW, True)["passed"]


def test_samples_that_overlap_cleanup_are_rejected():
    during = batch(False)
    during["results"][0]["finished_at"] = "2026-11-20T12:00:06+00:00"
    assert not evaluate_trial("disconnect", batch(), during, batch(), RUN, WINDOW, True)["passed"]


@pytest.mark.parametrize("problem", ["empty", "cleanup", "controller", "state", "baseline"])
def test_insufficient_or_failed_evidence_never_passes(problem):
    before, during, run = batch(), batch(False), copy.deepcopy(RUN)
    if problem == "empty":
        during["results"] = []
    if problem == "cleanup":
        run["actions"][0]["cleanup_verified"] = False
    if problem == "controller":
        run["status"] = "failed"
    if problem == "baseline":
        before = batch(False)
    assert not evaluate_trial("disconnect", before, during, batch(), run,
                              WINDOW, problem != "state")["passed"]


def test_probe_uses_an_address_on_the_shared_network():
    class Docker:
        def container_id(self, service):
            return "server-container"

        def docker(self, arguments):
            networks = ({"other": {"IPAddress": "192.0.2.8"},
                         "shared": {"IPAddress": "192.0.2.9"}}
                        if arguments[-1] == "server-container" else {"shared": {}})
            return SimpleNamespace(stdout=json.dumps(networks))

    assert probe_address(Docker(), "qa-probe") == "http://192.0.2.9:5000"


def test_probe_rejects_a_missing_shared_network():
    class Docker:
        def container_id(self, service):
            return "server-container"

        def docker(self, arguments):
            return SimpleNamespace(stdout=json.dumps({arguments[-1]: {"IPAddress": "192.0.2.8"}}))

    with pytest.raises(RuntimeError, match="shared IPv4"):
        probe_address(Docker(), "qa-probe")
