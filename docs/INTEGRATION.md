# FaultLab Integration Reference

This document describes the **current implemented behavior** of FaultLab's Docker/client/server/baseline/reset foundation, as it exists in the code today. It is not a design spec and nothing here is frozen — it describes what the system currently does, and it will change as the team integrates fault injection and recording/replay.

For anything involving Fidel's or Chidera's components, this document intentionally does not propose names, fields, APIs, or schemas (see "Team Decision Required" at the end).

## Current Implemented Interfaces

### `GET /health`

**Purpose:** a liveness/readiness check — confirms the server process is running and able to respond.

**Response:** always `200`, body:
```json
{"status": "healthy"}
```
There is currently no unhealthy response from this endpoint — if the process can respond at all, it reports healthy.

### `POST /process`

**Request shape:**
```json
{"request_id": "req-001", "value": 10}
```
`request_id` can be any JSON value that round-trips (the server just echoes it back); `value` must be numeric.

**Successful response** (`200`):
```json
{"request_id": "req-001", "status": "success", "result": 20}
```
The server currently doubles `value` (`result = value * 2`).

**Current `400` error cases**, all returning `{"status": "error", "message": "..."}` as plain JSON (never an HTML error page, and never an unhandled 500 for these cases):
- The request body is missing, empty, malformed JSON, or valid JSON that isn't an object (e.g. `null`) → `"a JSON object body is required"`.
- `request_id` or `value` is missing → `"request_id and value are required"`.
- `value` is present but not numeric → `"value must be a number"`.

**`value` must be numeric, and `bool` is explicitly rejected.** In Python, `bool` is technically a subclass of `int`, so `True`/`False` would otherwise silently be accepted as valid numbers (and double to `2`/`0`). The server explicitly checks for this and returns the same `"value must be a number"` error for a boolean `value`.

### `client/client.py`

**What it does:** a simple, one-shot demonstration client. It calls `/health`, then calls `/process` once with a fixed test value, and reports pass/fail for each.

**Configuration (environment variables):**
- `SERVER_URL` — default `http://127.0.0.1:5000`.
- `REQUEST_TIMEOUT_SECONDS` — default `5`. Must be a number greater than `0`. An invalid value (non-numeric, zero, or negative) prints a clear `Invalid configuration: ...` message and exits immediately with code `1`, before any network call is made.

**Health validation:** `check_health()` only reports success if *all* of the following hold — the request completes without a connection/timeout error, the HTTP status is `200`, the body parses as JSON, and the body is `{"status": "healthy"}`. A `200` with an unexpected or unparseable body is treated as a failure, not a pass.

**Process-response validation:** `run_process()` only reports success if the request completes, the status is `200`, the body parses as JSON, the returned `request_id` matches what was sent, `status == "success"`, and `result` equals the expected value. Any mismatch is reported as a failure with a descriptive message, never a crash.

**Exit codes:** `0` if both the health check and the process check pass; `1` if either fails, or if configuration is invalid.

**No retries or automatic recovery.** Each check is attempted exactly once. There is no retry loop, no reconnect behavior, and no self-healing — a failure is reported immediately as a failure.

### `baseline/baseline.py`

**Purpose:** sends a configurable number of `/process` requests to the server, measures latency per request, validates each response the same way the client does, and saves aggregate statistics to a JSON file. Used to characterize normal (fault-free) system behavior for later comparison.

**Configuration (environment variables), loaded by `load_config()`:**
- `SERVER_URL` — default `http://127.0.0.1:5000`.
- `BASELINE_REQUESTS` — default `20`. Must be an integer `>= 1`.
- `REQUEST_TIMEOUT_SECONDS` — default `3`. Must be a number `> 0`.
- `HEALTH_TIMEOUT_SECONDS` — default `30`. Must be a number `> 0`.

**Validation:** any invalid value (non-numeric, or out of the ranges above) prints a clear `Invalid configuration: ...` message and exits with code `1` before the server is ever contacted.

**Output file location:** `results/baseline_<UTC timestamp>.json` (e.g. `results/baseline_20261021T073133Z.json`), relative to the current working directory — this is `results/` under `/app` inside the `baseline` container, which the Compose file mounts to `./results` on the host.

**Current baseline JSON fields:**
```json
{
  "server_url": "...",
  "requests_requested": 20,
  "started_at": "ISO-8601 UTC timestamp",
  "finished_at": "ISO-8601 UTC timestamp",
  "results": [
    {
      "request_id": "baseline-0000",
      "input_value": 10,
      "expected_result": 20,
      "observed_result": 20,
      "http_status": 200,
      "success": true,
      "latency_ms": 12.3,
      "error": null
    }
  ],
  "summary": {
    "total_requests": 20,
    "successful_requests": 20,
    "failed_requests": 0,
    "success_rate": 100.0,
    "latency_ms": {"min": 0.0, "max": 0.0, "mean": 0.0, "median": 0.0, "stddev": null}
  }
}
```
`success_rate` is a percentage (`0`-`100`). `stddev` is `null` unless there are at least two successful latency measurements.

**Success/failure behavior and exit codes:** if the server never becomes healthy within `HEALTH_TIMEOUT_SECONDS`, the script prints a message and exits with code `1` without sending any `/process` requests. Otherwise, it always runs the full configured number of requests — individual request failures are recorded in the results file (`success: false`, with an `error` message) but do **not** stop the run or change the exit code. A clean exit code `0` means the run completed and a results file was written; it does **not** by itself mean every request succeeded — that must be read from the `summary` in the results file.

### `reset.py`

**What it currently resets:** the container-level environment only. It runs `docker compose down` (stopping and removing all current containers/network), then `docker compose up -d --build server` (rebuilding and starting a clean `server` container from current source), then verifies the new server is healthy and behaves correctly.

**What it does NOT yet reset:** it does not touch or restart the `client`/`baseline` containers, and it does **not** clean up any fault-injection state (e.g. `tc`/`netem` rules). There is a marked integration point in the code (`# Fault-injection cleanup (Fidel's scenario-control work) hooks in here once it exists.`) for that to be added later — see "Team Decision Required" below.

**Configuration:** `HEALTH_TIMEOUT_SECONDS` (default `30`, must be a number `> 0`) and `SERVER_URL` (default `http://127.0.0.1:5000`), loaded by `load_config()`. An invalid `HEALTH_TIMEOUT_SECONDS` prints a clear message and exits with code `1` before any Docker command runs.

**`RESET PASSED` / `RESET FAILED` behavior:** the script prints exactly one of these two lines near the end of its run. `RESET FAILED` is always followed by a short reason on the same or a preceding line (e.g. which Docker command failed and its exit status, that the server never became healthy, or that the final verification request failed).

**Health and `/process` verification:** after rebuilding the server and confirming it passes `wait_for_health`, `reset.py` makes its own direct `GET /health` call (expects `200`) and a `POST /process` call with `{"request_id": "reset-check", "value": 10}` (expects `200` and `result == 20`) before declaring success.

**Exit codes:** `0` on `RESET PASSED`. `1` on any failure path — a failed `docker compose` command (including Docker not being installed/running), the server never becoming healthy, or either verification request failing or returning an unexpected result.

### Docker / Compose

**Current services** (exactly as defined in `compose.yaml`): `server`, `client`, `baseline`.

- **`server`** — builds from `server/Dockerfile`, published on host port `5000` (`5000:5000`), has a Docker healthcheck that runs `python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health', timeout=2)"` every 5 seconds (3-second timeout, 5 retries, 5-second start period).
- **`client`** — builds from `client/Dockerfile`, `SERVER_URL=http://server:5000`, `depends_on: server` with `condition: service_healthy` (waits for the healthcheck, not just container start).
- **`baseline`** — builds from `baseline/Dockerfile`, `SERVER_URL=http://server:5000`, same `depends_on: service_healthy`, mounts `./results:/app/results`, and is gated behind `profiles: [baseline]` — **it is currently still profile-based and does not start on a plain `docker compose up`.** It's run explicitly, e.g. `docker compose run --rm baseline` (optionally with `--build` to guarantee the current source is used).

**Network behavior:** inside Compose's network, services reach the server at `http://server:5000` — `server` is the Compose service name, resolved via Docker's internal DNS. There is no other network configuration (no custom networks, no exposed ports beyond `5000` on `server`).

## Team Decision Required

The following are explicitly **not** designed or implied by this document or by any existing code, and are left for the team to decide together once Fidel's and Chidera's implementations exist:

- Scenario schema — TEAM DECISION REQUIRED
- Fault-controller interface — TEAM DECISION REQUIRED
- `tc`/`netem` cleanup interface — TEAM DECISION REQUIRED
- Process-failure interface — TEAM DECISION REQUIRED
- Shared run ID convention — TEAM DECISION REQUIRED
- Shared timestamp convention — TEAM DECISION REQUIRED
- Event schema — TEAM DECISION REQUIRED
- Recorder format — TEAM DECISION REQUIRED
- Replay format — TEAM DECISION REQUIRED
- Experiment bundle structure — TEAM DECISION REQUIRED
- Final orchestration between components — TEAM DECISION REQUIRED
