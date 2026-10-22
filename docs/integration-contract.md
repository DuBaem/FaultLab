# FaultLab Integration Contract (Version 1.0)

This document defines the minimum interface used by the baseline, fault-control,
recording/replay, and reset components.

AI-assistance disclosure: this document was drafted with OpenAI Codex on
October 22, 2026. The team must review, revise, understand, and document its use
before treating it as project work.

## First Integrated Path

`Baseline -> Inject -> Record -> Reset`

The first two integrated live faults are:

1. Server latency using `tc/netem delay`.
2. Server packet loss using `tc/netem loss`.

Network disconnection and process failure use the same scenario and event
interfaces but can be demonstrated after the two-fault path is verified.

## Scenario Input

- Format: JSON validated against `scenarios/scenario.schema.json`.
- Schema version: `1.0`.
- Scope: local Docker services only.
- Approved fault target: the long-running `server` service. The one-shot client
  remains a workload generator and is not a version 1.0 fault target.
- Approved fault types: `latency`, `packet_loss`, `disconnect`, and
  `process_failure`.
- Raw commands are never accepted from a scenario.
- Version 1.0 schedules one fault at a time to make cleanup deterministic.
- `duration_seconds` is the authoritative outage/fault duration.

Each action has a unique ID, target, start offset, duration, and typed parameter
object. Target names map to Compose service names through the top-level
`targets` array.

## Run Identity and Time

- Run ID format: `<scenario-id>-<UTC timestamp>-<8 random hex characters>`.
- Wall-clock timestamps: ISO 8601 in UTC.
- Schedule offsets and timing drift: monotonic seconds measured from run start.
- The run ID remains unchanged across every event in one execution.

## Experiment Folder

Each controller run writes:

```text
results/experiments/<run-id>/
  scenario.json
  events.jsonl
  summary.json
```

- `scenario.json`: exact validated input used for the run.
- `events.jsonl`: one JSON event per line, flushed as execution progresses.
- `summary.json`: final status, action timing, errors, and cleanup results.

Generated experiment folders are ignored by Git. A deliberate sample may be
copied into project documentation later after team review.

## Event Record

Every event contains:

- `sequence`
- `timestamp_utc`
- `run_id`
- `scenario_id`
- `event_type`

Action events also contain the applicable values from:

- `action_id`
- `fault_type`
- `target`
- `service`
- `planned_offset_seconds`
- `observed_offset_seconds`
- `parameters`
- `error`

Current event types include:

- `run_started`
- `fault_apply_started`
- `fault_applied`
- `fault_cleanup_started`
- `fault_cleaned`
- `run_failed`
- `emergency_cleanup_completed`
- `emergency_cleanup_failed`
- `run_completed`

The recorder/replay component may add observation events, but it should retain
these field names so runs can be compared without conversion.

## Cleanup Ownership

- The scenario controller owns immediate reversal of every fault it applies.
- Cleanup is attempted in a final recovery path when execution is interrupted.
- `reset.py` is the final environment-level recovery step.
- Reset recreates the server, verifies `/health` and `/process`, and confirms
  that no `netem` qdisc remains on `eth0`.
- A run is not successful when cleanup cannot be verified.

## Team Component Boundaries

- Dubem: baseline workload, Docker environment, health checks, reset, and final
  component integration.
- Fidel: scenario validation, fault adapters, timed execution, and immediate
  cleanup.
- Chidera: observation recording, replay, and original-versus-replay
  comparison using the agreed run folder and event fields.

Any interface change should be discussed by all three team members and updated
here before dependent code is merged.
