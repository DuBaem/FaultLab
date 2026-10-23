import os
import sys

import requests

DEFAULT_REQUEST_TIMEOUT_SECONDS = 5


def load_config():
    server_url = os.getenv("SERVER_URL", "http://127.0.0.1:5000")

    raw_timeout = os.getenv("REQUEST_TIMEOUT_SECONDS", str(DEFAULT_REQUEST_TIMEOUT_SECONDS))
    try:
        timeout_s = float(raw_timeout)
    except ValueError:
        print(f"Invalid configuration: REQUEST_TIMEOUT_SECONDS={raw_timeout!r} is not a number.")
        raise SystemExit(1)

    if timeout_s <= 0:
        print(f"Invalid configuration: REQUEST_TIMEOUT_SECONDS={timeout_s} must be greater than 0.")
        raise SystemExit(1)

    return server_url, timeout_s


def check_health(server_url, timeout_s):
    # A 200 by itself isn't enough proof the server is actually healthy -
    # the body has to say so too.
    try:
        response = requests.get(f"{server_url}/health", timeout=timeout_s)
    except requests.RequestException as exc:
        return False, f"health check failed: {exc}"

    if response.status_code != 200:
        return False, f"health check returned status {response.status_code}"

    try:
        body = response.json()
    except ValueError:
        return False, "health check response was not valid JSON"

    if not isinstance(body, dict) or body.get("status") != "healthy":
        return False, f"health check returned unexpected body: {body}"

    return True, "server is healthy"


def run_process(server_url, request_id, value, timeout_s):
    expected_result = value * 2
    payload = {"request_id": request_id, "value": value}

    try:
        response = requests.post(f"{server_url}/process", json=payload, timeout=timeout_s)
    except requests.RequestException as exc:
        return False, f"process request failed: {exc}"

    if response.status_code != 200:
        return False, f"process request returned status {response.status_code}"

    try:
        body = response.json()
    except ValueError:
        return False, "process response was not valid JSON"

    if body.get("request_id") != request_id:
        return False, f"process response had the wrong request_id: {body.get('request_id')!r}"

    if body.get("status") != "success":
        return False, f"process response reported failure: {body}"

    if body.get("result") != expected_result:
        return False, f"process response had the wrong result: expected {expected_result}, got {body.get('result')}"

    return True, f"process request succeeded, result={body.get('result')}"


def main():
    server_url, timeout_s = load_config()

    health_ok, health_detail = check_health(server_url, timeout_s)
    print(f"Health: {'PASS' if health_ok else 'FAIL'} - {health_detail}")

    process_ok, process_detail = run_process(server_url, "req-001", 10, timeout_s)
    print(f"Process: {'PASS' if process_ok else 'FAIL'} - {process_detail}")

    if not (health_ok and process_ok):
        sys.exit(1)


if __name__ == "__main__":
    main()
