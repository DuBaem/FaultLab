# FaultLab fault control guide

Fidel's component validates a scenario, applies its faults at the scheduled
times, reverses them, and records the execution events. This guide covers the
four local faults and the checks used before a demonstration.

## Start and check the environment

Open Docker Desktop and wait for the engine to run. Open PowerShell in the
FaultLab repository. Activate the project environment if needed:

```powershell
.\.venv\Scripts\Activate.ps1
docker compose up -d --build --wait server
docker compose build baseline
python -m pytest tests/
```

All commands below run from the same repository folder. Faults target the local
Compose `server`. Its `NET_ADMIN` capability permits container traffic control.
Do not run two controllers, resets, or experiments against this stack at once.

## Run one scenario

Check a scenario without changing Docker:

```powershell
python -m faultlab.controller scenarios/valid-latency.json --dry-run
```

Remove `--dry-run` to apply it. The other examples are
`valid-packet-loss.json`, `valid-disconnect.json`, and
`valid-process-failure.json` in `scenarios/`.

In another terminal, start the normal workload before the live scenario:

```powershell
docker compose run --rm -e BASELINE_REQUESTS=40 -e REQUEST_INTERVAL_SECONDS=0.25 baseline
```

The baseline output covers the whole request sequence. Use the safety runner
below for a direct before/during/after check. A baseline exit code of 0 means
the workload completed and saved results; inspect its success and failure counts.

## What each fault does

| Fault | Mechanism | What to observe | Cleanup |
| --- | --- | --- | --- |
| Latency | `tc/netem` delays traffic leaving server `eth0` | Increased measured response time | Delete qdisc and verify no `netem` remains |
| Packet loss | `tc/netem` drops a configured percentage of outgoing packets | Retransmission delays or request failures | Delete qdisc and verify |
| Disconnection | Disconnect server from its Docker networks | Requests cannot reach server | Reconnect original networks with the service alias |
| Process failure | Send allowlisted `SIGTERM` or `SIGKILL` | Service stops responding | Start service and wait for health |

HTTP latency is not identical to one configured packet delay. New connections,
TCP retransmissions, and the Docker environment affect what the application
observes. A packet-drop percentage also does not equal an HTTP failure rate [1].

## Repeatable safety check

```powershell
python -m faultlab.safety_check --trials 2
```

This runs two trials of every fault and one controlled interruption. Each
normal trial collects 8 requests before, 3 during, and 8 after an eight-second
fault. It checks that all during-fault requests fit entirely between the
`fault_applied` and `fault_cleanup_started` events. Before/during probes use the
server's current Docker IP to avoid resolver delays extending outage samples.
Recovery probes use `http://server:5000`, checking that the normal service name
works again.

Settings are 250 ms delay without jitter, 100% packet loss, complete network
disconnection, and `SIGKILL`. The 100% loss case tests a complete egress outage;
it is not an estimate of random-loss behavior at 25%.

Each trial requires a healthy baseline, an observed fault effect, successful
controller cleanup, no residual `netem`, restored network membership, and all
recovery requests succeeding. The interruption check deliberately raises a
Python `KeyboardInterrupt` after applying latency and verifies cleanup. It
exercises the Ctrl+C recovery path without requiring an interactive keystroke.

Results are saved in a unique folder under `results/fault-safety/`:

- `report.json`: raw requests, checks, run IDs, and interruption evidence.
- `summary.csv`: one compact row per normal trial.
- `runs/`: scenario snapshots, event logs, and controller summaries.
- `interrupted/`: the deliberately failed run and emergency-cleanup events.

Exit code 0 means every check passed. These are fault-safety checks; replay and
original-versus-replay comparison remain part of the recorder/replay integration.

## Failure recovery

If normal execution is interrupted, allow cleanup to finish. Docker commands
have a 30-second timeout [2]. An error is reported if rollback cannot complete.
If the stack is left unavailable, restore Docker and run:

```powershell
python reset.py
```

Confirm `RESET PASSED`. Reset checks `/health`, `/process`, and absence of an
active `netem` rule. Run another baseline before continuing. Closing the
controller forcibly or stopping Docker can bypass Python cleanup.

## Rehearsal checklist

1. Explain why the scenario is accepted and an unapproved target is rejected.
2. Show an ordinary successful baseline.
3. Explain and run one live fault with observable requests.
4. Open that run's scenario, events, and summary. Explain planned versus observed times.
5. Show cleanup, healthy recovery, and the interruption evidence.
6. Explain the component boundary: immediate fault cleanup belongs here; recording/replay comparison is integrated separately.

The guide is prepared. Each presenter still needs to practice these steps and
understand the code before claiming a completed rehearsal.

## References

[1] S. Hemminger, F. Ludovici, and H. P. Pfeifer, "tc-netem(8)," *Linux manual pages*. [Online]. Available: https://man7.org/linux/man-pages/man8/tc-netem.8.html. [Accessed: Nov. 20, 2026].

[2] Python Software Foundation, "subprocess — Subprocess management," *Python 3.12 documentation*. [Online]. Available: https://docs.python.org/3.12/library/subprocess.html. [Accessed: Nov. 20, 2026].

Prepared with OpenAI Codex assistance, November 20, 2026.
