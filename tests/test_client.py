import os
from unittest.mock import patch, MagicMock

import pytest
import requests

import client


def make_response(status_code, body=None, raise_on_json=False):
    response = MagicMock()
    response.status_code = status_code
    if raise_on_json:
        response.json.side_effect = ValueError("not valid json")
    else:
        response.json.return_value = body
    return response


# --- check_health ---

def test_check_health_success():
    response = make_response(200, {"status": "healthy"})
    with patch.object(client.requests, "get", return_value=response):
        ok, detail = client.check_health("http://server", 3)

    assert ok is True


def test_check_health_fails_on_wrong_status_field():
    response = make_response(200, {"status": "not-healthy"})
    with patch.object(client.requests, "get", return_value=response):
        ok, detail = client.check_health("http://server", 3)

    assert ok is False


def test_check_health_fails_on_invalid_json():
    response = make_response(200, raise_on_json=True)
    with patch.object(client.requests, "get", return_value=response):
        ok, detail = client.check_health("http://server", 3)

    assert ok is False


def test_check_health_fails_on_connection_error():
    with patch.object(client.requests, "get", side_effect=requests.ConnectionError("refused")):
        ok, detail = client.check_health("http://server", 3)

    assert ok is False
    assert "refused" in detail


def test_check_health_fails_on_timeout():
    with patch.object(client.requests, "get", side_effect=requests.Timeout("timed out")):
        ok, detail = client.check_health("http://server", 3)

    assert ok is False


def test_check_health_fails_on_non_200_status():
    response = make_response(500, {"status": "healthy"})
    with patch.object(client.requests, "get", return_value=response):
        ok, detail = client.check_health("http://server", 3)

    assert ok is False


# --- run_process ---

def test_run_process_fails_on_connection_error():
    with patch.object(client.requests, "post", side_effect=requests.ConnectionError("refused")):
        ok, detail = client.run_process("http://server", "req-001", 10, 3)

    assert ok is False
    assert "refused" in detail


def test_run_process_fails_on_timeout():
    with patch.object(client.requests, "post", side_effect=requests.Timeout("timed out")):
        ok, detail = client.run_process("http://server", "req-001", 10, 3)

    assert ok is False
    assert "timed out" in detail


def test_run_process_fails_on_non_200_response():
    response = make_response(500, {"status": "error"})
    with patch.object(client.requests, "post", return_value=response):
        ok, detail = client.run_process("http://server", "req-001", 10, 3)

    assert ok is False


def test_run_process_fails_on_invalid_json_response():
    response = make_response(200, raise_on_json=True)
    with patch.object(client.requests, "post", return_value=response):
        ok, detail = client.run_process("http://server", "req-001", 10, 3)

    assert ok is False


def test_run_process_fails_on_wrong_request_id():
    response = make_response(200, {"request_id": "different-id", "status": "success", "result": 20})
    with patch.object(client.requests, "post", return_value=response):
        ok, detail = client.run_process("http://server", "req-001", 10, 3)

    assert ok is False


def test_run_process_fails_on_wrong_result():
    response = make_response(200, {"request_id": "req-001", "status": "success", "result": 999})
    with patch.object(client.requests, "post", return_value=response):
        ok, detail = client.run_process("http://server", "req-001", 10, 3)

    assert ok is False


def test_run_process_succeeds_on_matching_response():
    response = make_response(200, {"request_id": "req-001", "status": "success", "result": 20})
    with patch.object(client.requests, "post", return_value=response):
        ok, detail = client.run_process("http://server", "req-001", 10, 3)

    assert ok is True


# --- load_config ---

def test_load_config_valid():
    with patch.dict(os.environ, {"SERVER_URL": "http://server", "REQUEST_TIMEOUT_SECONDS": "5"}, clear=False):
        server_url, timeout_s = client.load_config()

    assert server_url == "http://server"
    assert timeout_s == 5.0


@pytest.mark.parametrize("raw_value", ["abc", "0", "-1"])
def test_load_config_rejects_invalid_timeout(raw_value):
    with patch.dict(os.environ, {"REQUEST_TIMEOUT_SECONDS": raw_value}, clear=False):
        with pytest.raises(SystemExit):
            client.load_config()
