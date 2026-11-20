# How the client, server, baseline, and reset fit together

Use this page when you're connecting another component to the server or trying to explain a run that finished with failed requests. The [scenario and event contract](integration-contract.md) covers the controller's side of the same experiment.

## What the server returns

`GET /health` returns HTTP 200 and `{"status":"healthy"}` when the Flask handler can answer. To check that the server can also do its job, send a request to `POST /process`:

```json
{"request_id": "req-001", "value": 10}
```

A successful response has HTTP status 200. The server echoes the ID and doubles the number:

```json
{"request_id": "req-001", "status": "success", "result": 20}
```

The ID can be any non-null JSON value. The server accepts integers and decimals for `value`. It rejects booleans so that sending `true` by mistake won't produce the number 2. For HTTP 400, look at the `message` field alongside `"status": "error"`:

| What the server received | Message |
| --- | --- |
| Empty body, malformed JSON, or a JSON value other than an object | `a JSON object body is required` |
| Missing or null `request_id` or `value` | `request_id and value are required` |
| A nonnumeric `value`, including a boolean | `value must be a number` |

## Which check should I run?

| Program | What it checks | What exit code 0 tells you |
| --- | --- | --- |
| [Client](../client/client.py) | Calls `/health` once and sends one known value to `/process`. Checks HTTP status, the health message, the echoed ID, the success flag, and the doubled value. | Both checks passed. The client exits with 1 if either fails. |
| [Baseline](../baseline/baseline.py) | Waits for HTTP 200 from `/health`, then sends a series of timed `/process` requests and checks their answers. | The workload finished and saved a file. Check the success count inside it to see how many requests passed. |
| [Reset](../reset.py) | Takes down this Compose stack, rebuilds the server, checks health and processing, then inspects the server's traffic-control rules. | Reset printed `RESET PASSED`. The server answered correctly and the interface check found no active `netem` rule. |

The client tries each endpoint once. The baseline continues after an individual request fails so that you can see when failures start and when the service recovers. If the baseline times out waiting for a healthy server, it exits with 1 before sending the workload.

## Settings

| Variable | Used by | Default and meaning |
| --- | --- | --- |
| `SERVER_URL` | Client, baseline, reset | Defaults to `http://127.0.0.1:5000` on the host. Compose sets `http://server:5000` for the client and baseline containers. |
| `BASELINE_REQUESTS` | Baseline | 20 requests. Choose a whole number of at least 1. |
| `REQUEST_TIMEOUT_SECONDS` | Client, baseline | 5 seconds for the client, 3 for the baseline. Choose a positive value. |
| `HEALTH_TIMEOUT_SECONDS` | Baseline, reset | 30 seconds to wait for the server. Choose a positive value. |
| `REQUEST_INTERVAL_SECONDS` | Baseline | 0 seconds between requests. Increase it to spread a workload across a fault. |
| `RESULTS_DIR` | Baseline | Defaults to `results` relative to the working directory. Compose mounts the container's `/app/results` at `./results` on the host. |

Each program checks its numeric settings before starting its work. For example, setting `BASELINE_REQUESTS=0` reports an invalid configuration and exits with 1. To run a small baseline with a valid setting, use `docker compose run --rm -e BASELINE_REQUESTS=5 baseline`.

## Reading a baseline file

Look for `results/baseline_<UTC timestamp>.json`. The top level records `server_url`, `requests_requested`, `started_at`, `finished_at`, `results`, and `summary`. Start with `summary`, then look up a request in `results` if you need to explain a failure.

| Field | How to use it |
| --- | --- |
| `total_requests`, `successful_requests`, `failed_requests`, `success_rate` under `summary` | Read the counts together. The rate is a percentage from 0 to 100. |
| `summary.latency_ms` | Gives the minimum, maximum, mean, median, and sample standard deviation for successful requests. With no successes these values are null. `stddev` needs two successful timings. |
| `request_id`, `input_value`, `expected_result`, `observed_result` | Match a single request to its answer. |
| `http_status`, `success`, `latency_ms`, `error` | Distinguish a wrong answer from a timeout. A timeout can leave the HTTP status and elapsed time null. |

## What Docker starts

The [Compose file](../compose.yaml) defines three services. The Flask `server` publishes port 5000 and adds `NET_ADMIN` so the controller can change traffic rules inside that container. Its health check calls `/health` using Python every five seconds, with a three-second timeout, five retries, and a five-second start period.

The `client` runs once after the server is healthy. The `baseline` service waits for the same health check but has its own Compose profile. Start it explicitly with `docker compose run --rm --build baseline`. Both services use Docker's DNS to reach `server` on the default Compose network.

## What reset verifies

Run `python reset.py` from the repository root. It runs `docker compose down`, then `docker compose up -d --build server`. After the new server answers its health check, reset makes a fresh `GET /health` and sends `{"request_id":"reset-check","value":10}` to `/process`. It expects HTTP 200 and a result of 20. Finally, it inspects `eth0` for a leftover `netem` queue.

If you see `RESET FAILED`, read the reason on that line. It identifies the step to investigate, such as a Docker error, a health timeout, an unexpected answer, or a failed queue check. A successful reset leaves the server running so the next person can take a fresh baseline.

## Decisions for recorder and replay integration

When integrating the recorder, agree on which observations belong to each run, how replay reads the saved input, and how the comparison pairs up results. Use the controller's existing run ID and event fields to link the records. If a field needs to change, update the contract together before merging the code that reads it.
