import os

import pytest
import requests

import baseline

SERVER_URL = os.getenv("SERVER_URL", "http://127.0.0.1:5000")


def server_is_running():
    try:
        return requests.get(f"{SERVER_URL}/health", timeout=1).status_code == 200
    except requests.RequestException:
        return False


# This test needs a real server, so it's skipped unless one is actually up
# (e.g. `docker compose up -d server` before running pytest).
@pytest.mark.skipif(not server_is_running(), reason="no live server at SERVER_URL")
def test_run_request_against_live_server():
    result = baseline.run_request(SERVER_URL, "integration-check", 10, 3)

    assert result["success"] is True
    assert result["observed_result"] == 20
