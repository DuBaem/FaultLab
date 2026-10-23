import os
import subprocess
import sys
import time

import requests


def load_config():
    server_url = os.getenv("SERVER_URL", "http://127.0.0.1:5000")

    raw_timeout = os.getenv("HEALTH_TIMEOUT_SECONDS", "30")
    try:
        health_timeout = float(raw_timeout)
    except ValueError:
        print(f"Invalid configuration: HEALTH_TIMEOUT_SECONDS={raw_timeout!r} is not a number.")
        raise SystemExit(1)

    if health_timeout <= 0:
        print(f"Invalid configuration: HEALTH_TIMEOUT_SECONDS={health_timeout} must be greater than 0.")
        raise SystemExit(1)

    return server_url, health_timeout


def stop_environment():
    # Tear down whatever is currently running so the next build starts clean.
    subprocess.run(["docker", "compose", "down"], check=True)


def recreate_server():
    subprocess.run(["docker", "compose", "up", "-d", "--build", "server"], check=True)


def wait_for_health(server_url, timeout_s):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{server_url}/health", timeout=2)
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


def verify_process(server_url):
    # Reuse the same predictable workload the baseline uses: value=10 should always come back as 20.
    response = requests.post(
        f"{server_url}/process",
        json={"request_id": "reset-check", "value": 10},
        timeout=3,
    )
    return response.status_code == 200 and response.json().get("result") == 20


def main():
    server_url, health_timeout = load_config()

    try:
        print("Stopping current environment...")
        stop_environment()

        print("Recreating a clean server...")
        recreate_server()
    except subprocess.CalledProcessError as exc:
        print(f"RESET FAILED: '{' '.join(exc.cmd)}' exited with status {exc.returncode}.")
        return 1
    except FileNotFoundError:
        print("RESET FAILED: could not run the 'docker' command. Is Docker installed and running?")
        return 1

    print(f"Waiting for server at {server_url} to become healthy...")
    if not wait_for_health(server_url, health_timeout):
        print("RESET FAILED: server never became healthy.")
        return 1

    try:
        health_response = requests.get(f"{server_url}/health", timeout=3)
        if health_response.status_code != 200:
            print(f"RESET FAILED: /health returned status {health_response.status_code}.")
            return 1

        if not verify_process(server_url):
            print("RESET FAILED: /process did not return the expected result for value=10.")
            return 1

    except requests.RequestException as exc:
        print(f"RESET FAILED: {exc}")
        return 1

    # Fault-injection cleanup (Fidel's scenario-control work) hooks in here once it exists.

    print("RESET PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
