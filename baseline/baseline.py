import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

SERVER_URL = os.getenv("SERVER_URL", "http://127.0.0.1:5000")
BASELINE_REQUESTS = int(os.getenv("BASELINE_REQUESTS", "20"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "3"))
HEALTH_TIMEOUT_SECONDS = float(os.getenv("HEALTH_TIMEOUT_SECONDS", "30"))
REQUEST_INTERVAL_SECONDS = float(os.getenv("REQUEST_INTERVAL_SECONDS", "0"))

# Relative to the current working directory so this matches both a local run
# from the repo root and the container, where WORKDIR and the results volume
# mount both land on "results" under /app.
RESULTS_DIR = Path(os.getenv("RESULTS_DIR", "results"))


def wait_for_health(server_url, timeout_s):
    # Give the server a chance to finish starting instead of failing on the first try.
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


def run_request(server_url, request_id, value, timeout_s):
    expected_result = value * 2
    result = {
        "request_id": request_id,
        "input_value": value,
        "expected_result": expected_result,
        "observed_result": None,
        "http_status": None,
        "success": False,
        "latency_ms": None,
        "error": None,
    }

    payload = {"request_id": request_id, "value": value}

    try:
        # Start timing immediately before the request so latency reflects the network call only.
        start = time.perf_counter()
        response = requests.post(f"{server_url}/process", json=payload, timeout=timeout_s)
        latency_ms = (time.perf_counter() - start) * 1000

        result["http_status"] = response.status_code
        result["latency_ms"] = latency_ms

        body = response.json()

        # A request only counts as a pass if every field matches what we expect back.
        is_valid = (
            response.status_code == 200
            and body.get("request_id") == request_id
            and body.get("status") == "success"
            and body.get("result") == expected_result
        )

        if is_valid:
            result["success"] = True
            result["observed_result"] = body.get("result")
        else:
            result["observed_result"] = body.get("result")
            result["error"] = f"unexpected response: {body}"

    except (requests.RequestException, ValueError) as exc:
        # Record the failure instead of letting one bad request stop the whole run.
        result["error"] = str(exc)

    return result


def calculate_summary(results):
    total = len(results)
    successes = [r for r in results if r["success"]]
    failures = total - len(successes)

    summary = {
        "total_requests": total,
        "successful_requests": len(successes),
        "failed_requests": failures,
        "success_rate": (len(successes) / total * 100) if total else 0,
        "latency_ms": {
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
            "stddev": None,
        },
    }

    latencies = [r["latency_ms"] for r in successes if r["latency_ms"] is not None]
    if latencies:
        summary["latency_ms"]["min"] = min(latencies)
        summary["latency_ms"]["max"] = max(latencies)
        summary["latency_ms"]["mean"] = statistics.mean(latencies)
        summary["latency_ms"]["median"] = statistics.median(latencies)
        # Standard deviation needs at least two data points to mean anything.
        if len(latencies) >= 2:
            summary["latency_ms"]["stddev"] = statistics.stdev(latencies)

    return summary


def save_results(run_data, results_dir):
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = results_dir / f"baseline_{timestamp}.json"
    output_path.write_text(json.dumps(run_data, indent=2), encoding="utf-8")
    return output_path


def main():
    print(f"Waiting for server at {SERVER_URL} to become healthy...")
    if not wait_for_health(SERVER_URL, HEALTH_TIMEOUT_SECONDS):
        print("Server never became healthy. Aborting baseline run.")
        raise SystemExit(1)

    print(f"Server is healthy. Running {BASELINE_REQUESTS} requests...")

    started_at = datetime.now(timezone.utc).isoformat()
    results = []
    for i in range(BASELINE_REQUESTS):
        request_id = f"baseline-{i:04d}"
        results.append(run_request(SERVER_URL, request_id, 10, REQUEST_TIMEOUT_SECONDS))
        if REQUEST_INTERVAL_SECONDS > 0 and i < BASELINE_REQUESTS - 1:
            time.sleep(REQUEST_INTERVAL_SECONDS)
    finished_at = datetime.now(timezone.utc).isoformat()

    summary = calculate_summary(results)

    run_data = {
        "server_url": SERVER_URL,
        "requests_requested": BASELINE_REQUESTS,
        "started_at": started_at,
        "finished_at": finished_at,
        "results": results,
        "summary": summary,
    }

    output_path = save_results(run_data, RESULTS_DIR)

    print(
        f"Baseline complete: {summary['successful_requests']}/"
        f"{summary['total_requests']} succeeded ({summary['success_rate']:.1f}%)"
    )
    if summary["latency_ms"]["mean"] is not None:
        print(f"Latency (ms) - min: {summary['latency_ms']['min']:.1f}, "
              f"max: {summary['latency_ms']['max']:.1f}, "
              f"mean: {summary['latency_ms']['mean']:.1f}, "
              f"median: {summary['latency_ms']['median']:.1f}")
    print(f"Results saved to {output_path}")


if __name__ == "__main__":
    main()
