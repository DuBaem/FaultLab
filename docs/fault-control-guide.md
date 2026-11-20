# Running a fault and checking recovery

For a first demo, try the latency example. The client can still get the right answer while the delay is active, so the change to watch is **how long the answer takes**. Then try a disconnect. The question there is whether the client can reach the server again by its usual name.

## Set up two terminals

Open Docker Desktop. In PowerShell, go to the FaultLab folder and activate the Python environment from the [README](../README.md). In the first terminal, run these commands to start the server, build the workload image, and preview the latency scenario.

```powershell
docker compose up -d --build --wait server
docker compose build baseline
python -m faultlab.controller scenarios/valid-latency.json --dry-run
```

The dry run checks the schedule and writes a run folder without applying a fault. To see why a scenario might be rejected, try `python -m faultlab.scenario_validator scenarios/invalid-target.json`. The error points to the service name. FaultLab accepts the local `server` as its target.

Open a second terminal in the same folder. Start a workload with enough requests to span the delay:

```powershell
docker compose run --rm -e BASELINE_REQUESTS=40 -e REQUEST_INTERVAL_SECONDS=0.25 baseline
```

When the workload starts sending requests, switch to the first terminal and run:

```powershell
python -m faultlab.controller scenarios/valid-latency.json
```

Let the workload and controller both finish. The workload saves individual request times under `results/`. The controller prints the path to its own run folder. Compare the requested delay in `scenario.json` with the times in the workload file, and look for the cleanup event in `events.jsonl`. To collect requests explicitly labeled before, during, and after a fault, use the safety check below.

## What to watch for

| Example scenario | While the fault is active | How the controller cleans up |
| --- | --- | --- |
| [Latency](../scenarios/valid-latency.json) | The server delays outgoing packets. HTTP responses usually take longer. | Removes the queue rule on `eth0` and checks that `netem` is gone. |
| [Packet loss](../scenarios/valid-packet-loss.json) | Some outgoing packets are dropped. A request might take longer, time out, or succeed on the first try. | Removes the loss rule and checks the interface. |
| [Disconnect](../scenarios/valid-disconnect.json) | Other containers lose their route to the server. | Reconnects the original networks with the service alias. |
| [Process failure](../scenarios/valid-process-failure.json) | The server process stops answering. | Starts the service and waits for it to report healthy or running. |

A 250 ms packet delay can add more than 250 ms to an HTTP exchange. Several packets may travel before the client gets its answer. TCP can also retransmit a dropped packet, so the percentage of packets lost doesn't directly predict the percentage of failed requests [1].

## Repeat the safety check

With the server running and no other experiment using it, run:

```powershell
python -m faultlab.safety_check --trials 2
```

The runner tries each fault twice. In each trial it sends eight requests before the fault, three during its eight-second window, and eight after cleanup. Each during-fault request must start and finish between `fault_applied` and `fault_cleanup_started`. The probe uses the server's Docker IP before and during the fault to avoid waiting for DNS during an outage. After cleanup it switches back to `http://server:5000` to check the address the team normally uses.

The delay check sets 250 ms with no jitter and looks for a mean response time at least 100 ms above baseline. The other trials use 100% packet loss, a full disconnect, or `SIGKILL` and look for at least one failed request during the fault. Every trial also checks that the baseline passed, the original networks are back, the server is healthy, the queue is clean, and every recovery request succeeded.

Finally, the runner interrupts a delay using Python's `KeyboardInterrupt`. Look for a **failed experiment** in the interrupted run's summary and a **passed recovery check** in the overall report. That combination tells you the scenario ended early and the server recovered.

| Under `results/fault-safety/<run-folder>/` | What it tells you |
| --- | --- |
| `summary.csv` | One row per regular trial. Start here for the demo. |
| `report.json` | Individual requests, timestamps, pass criteria, and the interruption result. |
| `runs/` and `interrupted/` | The scenario, event log, and controller summary behind each result. |

## If the demo stops halfway through

Give the controller time to clean up. Its Docker commands have a 30-second timeout, and Docker may already have acted when a command times out [2]. If Docker stopped or you had to force the controller closed, bring Docker back up and run `python reset.py`. Wait for `RESET PASSED`, then run a fresh baseline. One person should operate the controller and reset for a given stack at a time.

## Rehearse the explanation

1. Show a healthy request and its doubled result.
2. Open the scenario and point to its target, start time, and duration.
3. Show what changed for the client, then find the matching events in the log.
4. Show the first successful requests after cleanup. Use the interrupted trial to explain what happens if the experiment ends early.
5. Hand off to the recording and replay section once you've shown where the controller saves its events.

OpenAI Codex helped prepare this guide on November 20, 2026.

## References

[1] S. Hemminger, F. Ludovici, and H. P. Pfeifer, "tc-netem(8)," *Linux manual pages*. [Online]. Available: https://man7.org/linux/man-pages/man8/tc-netem.8.html. [Accessed: Nov. 20, 2026].

[2] Python Software Foundation, "subprocess — Subprocess management," *Python 3.12 documentation*. [Online]. Available: https://docs.python.org/3.12/library/subprocess.html. [Accessed: Nov. 20, 2026].
