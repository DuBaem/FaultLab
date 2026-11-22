# How to read a FaultLab run (version 1.0)

When you're matching a client observation to a fault, check which run it belongs to and whether the fault was active at the time. The controller gives each run one ID and records when each fault actually starts and ends. This is the format to use when connecting the controller, recorder, and replay tools.

## Scenario input

Start with the [two-fault example](../scenarios/demo-latency-packet-loss.json). It names the local Compose service `server` and gives it the scenario name `api-server`. Each action refers to that name in its `target`. An action has its own unique ID, a fault type, a start offset in seconds, a duration, and parameters for that fault.

The [schema](../scenarios/scenario.schema.json) describes version `1.0`. The [validator](../faultlab/scenario_validator.py) also checks how fields relate to one another. Only the long-running local `server` can be a target. The client generates the workload. Scenarios accept data and the four fault names below. The controller rejects overlapping actions because cleaning up the first fault could undo the second.

| Fault type | What the action changes |
| --- | --- |
| `latency` | Delays outgoing server packets by `latency_ms`, with optional `jitter_ms`. |
| `packet_loss` | Drops a percentage of outgoing packets according to `loss_percent`. |
| `disconnect` | Disconnects the server from its Docker networks in both directions. |
| `process_failure` | Stops the server process using the selected signal. |

For all four faults, `duration_seconds` controls how long the controller waits after applying the fault before starting cleanup.

## One folder per run

The default path is `results/experiments/<run-id>/`. The ID combines the scenario ID, a UTC timestamp, and eight random hexadecimal characters. Repeating the same scenario produces a new ID. Every event in one run carries that same ID.

| File | What to look for |
| --- | --- |
| `scenario.json` | A copy of the validated input, including the requested start times, durations, and parameters. |
| `events.jsonl` | One JSON object per line, written as the run progresses. Read events in `sequence` order. |
| `summary.json` | The run status, dry-run flag, requested and completed action counts, observed timing, and errors. |

Local runs go in `results/`. For a worked example, open the [November 20 trial folders](evidence/fault-safety-2026-11-20/runs/).

## Reading the timeline

Every event includes `sequence`, `timestamp_utc`, `run_id`, `scenario_id`, and `event_type`. The timestamp is an ISO 8601 UTC time. Planned and observed offsets are seconds from the start of the run, measured against a monotonic clock for scheduling.

On a normal run, look for these events in order:

1. `run_started` opens the run.
2. `fault_apply_started` records the action and its parameters. `fault_applied` means the call to apply it has returned.
3. `fault_cleanup_started` marks the end of the measurement window. `fault_cleaned` records that the adapter finished removing the fault.
4. `run_completed` closes the run. Check the status in the summary to see whether it passed.

Action events carry whichever of these fields apply: `action_id`, `fault_type`, `target`, `service`, `planned_offset_seconds`, `observed_offset_seconds`, `parameters`, and `error`. Use the observed events to decide whether a request fell inside the fault window. A request sent at the planned start could reach the server before Docker finished applying the fault.

## Interrupted runs and cleanup

Fidel's controller handles immediate cleanup. If the event log stops accepting writes or someone presses Ctrl+C, the controller tries to undo active faults before it reports the failure. You may see `emergency_cleanup_completed` or `emergency_cleanup_failed` before `run_failed`. If the disk stopped accepting writes, the event log itself can be incomplete.

In the summary, `error` gives the primary failure, `cleanup_errors` lists problems undoing a fault, and `logging_errors` lists errors writing the recovery or final events. An interrupted experiment can correctly say `failed` even when its cleanup succeeds.

The Docker command timeout defaults to 30 seconds. A command can reach Docker just before the controller loses its reply. If that happens while applying a delay, packet loss, or a process fault, the adapter attempts to undo the change. For a disconnect, it tries to reconnect every original network and restore the service alias, even if one network reconnect fails.

Use one controller per stack. If the controller is forcibly killed or Docker stops, restore Docker and run `python reset.py`. Dubem's reset rebuilds the server, checks `/health` and `/process`, and verifies that `eth0` has no active `netem` queue.

## Integrating the recorder

The measured runner saves each trial under `results/series/<series-id>/<run-id>/`. Its `experiment.json` contains the scenario, confirmed controller events and timestamped HTTP requests. The workload and controller run on the same host. Requests always send 10 to the local server and expect 20 back. The separate Docker baseline still measures requests from inside the Compose network.

The action summary uses seconds from the controller's monotonic clock. Compare `planned_start_seconds`, `dispatch_seconds`, and `observed_start_seconds` to see when the controller meant to start, began applying the fault, and received confirmation. `apply_overhead_seconds` includes event logging and the Docker operation. The controller resolves the server container before starting the clock. It keeps each fault active for the requested duration after confirmation, even when a previous action finishes late.

Each HTTP request records start and finish in UTC. A request counts toward an action only when its entire lifetime fits between `fault_applied` and `fault_cleanup_started`. Requests that cross an edge keep the phase `boundary` in the timeline. A short window may contain no complete requests. The summary counts timed-out requests among HTTP failures and computes mean HTTP latency from successful responses only.

After each action, the live controller checks the server's original network membership and service alias, the network queue, and a fresh HTTP response. The next action waits for those checks. After each measured trial, four recovery probes must succeed before another trial starts. A passed trial can still contain HTTP failures during injection.

For repeats, `series.json` records the mean absolute difference between planned and confirmed start, and the sample standard deviation of trial mean HTTP times. Each comparison pairs requests by action and order within the confirmed window. It records both sample counts and how many pairs were available. The failure reproduction percentage uses only matched requests that failed in the original. With no such failures the value is null. A replay repeats the same scenario and input workload. Packet loss can select different packets on each run.

Dubem owns the baseline, reset, and end-to-end integration. Fidel owns scenario validation, fault timing, and immediate cleanup. Chidera owns observations, replay, and comparison. Keep the event names and run IDs when adding observations so a replay can be traced back to its original run. Discuss changes to a shared field with the people who read it before merging.

OpenAI Codex helped draft this contract on October 22, 2026, and revise it on November 20. The team must review, revise, understand, and document the AI-assisted work it uses for the course.
