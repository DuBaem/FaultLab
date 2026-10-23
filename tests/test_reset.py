import os
import subprocess
from unittest.mock import patch, MagicMock

import pytest
import requests

import reset


def make_response(status_code, body):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = body
    return response


# --- verify_process ---

def test_verify_process_succeeds_on_matching_response():
    response = make_response(200, {"result": 20})
    with patch.object(reset.requests, "post", return_value=response):
        assert reset.verify_process("http://server") is True


def test_verify_process_fails_on_wrong_result():
    response = make_response(200, {"result": 999})
    with patch.object(reset.requests, "post", return_value=response):
        assert reset.verify_process("http://server") is False


def test_verify_process_fails_on_non_200_status():
    response = make_response(500, {"result": 20})
    with patch.object(reset.requests, "post", return_value=response):
        assert reset.verify_process("http://server") is False


# --- wait_for_health ---

def test_wait_for_health_returns_false_on_timeout():
    with patch.object(reset.requests, "get", side_effect=requests.ConnectionError("refused")):
        assert reset.wait_for_health("http://server", 0.01) is False


# --- main() failure paths ---

def test_main_fails_cleanly_when_docker_compose_down_fails():
    with patch.object(reset, "stop_environment", side_effect=subprocess.CalledProcessError(1, ["docker", "compose", "down"])):
        exit_code = reset.main()

    assert exit_code == 1


def test_main_fails_cleanly_when_docker_is_not_found():
    with patch.object(reset, "stop_environment", side_effect=FileNotFoundError()):
        exit_code = reset.main()

    assert exit_code == 1


def test_main_fails_when_server_never_becomes_healthy():
    with patch.object(reset, "stop_environment", MagicMock()), \
         patch.object(reset, "recreate_server", MagicMock()), \
         patch.object(reset, "wait_for_health", return_value=False):
        exit_code = reset.main()

    assert exit_code == 1


def test_main_fails_when_process_verification_fails():
    health_response = make_response(200, {})
    with patch.object(reset, "stop_environment", MagicMock()), \
         patch.object(reset, "recreate_server", MagicMock()), \
         patch.object(reset, "wait_for_health", return_value=True), \
         patch.object(reset.requests, "get", return_value=health_response), \
         patch.object(reset, "verify_process", return_value=False):
        exit_code = reset.main()

    assert exit_code == 1


def test_main_succeeds_on_full_happy_path():
    health_response = make_response(200, {})
    with patch.object(reset, "stop_environment", MagicMock()), \
         patch.object(reset, "recreate_server", MagicMock()), \
         patch.object(reset, "wait_for_health", return_value=True), \
         patch.object(reset.requests, "get", return_value=health_response), \
         patch.object(reset, "verify_process", return_value=True), \
         patch.object(reset, "verify_no_active_netem", return_value=True):
        exit_code = reset.main()

    assert exit_code == 0


def test_main_fails_when_netem_cleanup_verification_fails():
    health_response = make_response(200, {})
    with patch.object(reset, "stop_environment", MagicMock()), \
         patch.object(reset, "recreate_server", MagicMock()), \
         patch.object(reset, "wait_for_health", return_value=True), \
         patch.object(reset.requests, "get", return_value=health_response), \
         patch.object(reset, "verify_process", return_value=True), \
         patch.object(reset, "verify_no_active_netem", return_value=False):
        exit_code = reset.main()

    assert exit_code == 1


# --- load_config ---

def test_load_config_valid():
    with patch.dict(os.environ, {"SERVER_URL": "http://server", "HEALTH_TIMEOUT_SECONDS": "15"}, clear=False):
        server_url, health_timeout = reset.load_config()

    assert server_url == "http://server"
    assert health_timeout == 15.0


@pytest.mark.parametrize("raw_value", ["abc", "0", "-1"])
def test_load_config_rejects_invalid_health_timeout(raw_value):
    with patch.dict(os.environ, {"HEALTH_TIMEOUT_SECONDS": raw_value}, clear=False):
        with pytest.raises(SystemExit):
            reset.load_config()
