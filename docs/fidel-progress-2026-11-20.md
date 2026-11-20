# Fidel's FaultLab progress as of November 20 2026

The scheduled fault-controller implementation is in `main`. This update adds
reliability fixes, 22 unit tests, measured fault-safety evidence, and a control
guide on `fidel/fault-reliability`. All 115 tests passed with Docker running.
Eight live fault trials and a controlled interruption check passed. Team review
and integration of this branch remain pending.

## Progress against the saved Gantt

The schedule used is `FaultLab_Gantt_Report2_Revised.xlsx`, the saved class
template revision in the Report 2 materials. Member 2 is Fidel Anyanwu. The
dates below are its planned task windows, not claimed actual start dates.

| Scheduled work | Planned dates in 2026 | Verified state on November 20 |
| --- | --- | --- |
| Fault interfaces, tc/netem, four adapters, validator/controller | Aug. 31–Oct. 25 | Existing implementation merged through PR #3. Existing tests retained. |
| Fault/controller integration and regression QA | Oct. 19–Nov. 8 | New regression checks pass alongside the baseline/reset and client/server tests. Branch review remains. |
| Reliability research and fault safety QA | Nov. 2–22 | Cleanup failure paths hardened. Eight live trials plus interruption recovery pass. Source notes and references prepared below; Fidel's personal reading still needs confirmation. |
| Fault results analysis and cross-checks | Nov. 16–Dec. 6 | Initial results and raw evidence captured. Broader loss levels, more trials, and team integration remain within this ongoing task. |
| Fault-control guide and demo rehearsal | Nov. 23–Dec. 13 | Guide prepared early. Presenter rehearsal is still to be completed. |

The group Gantt's dates, colors, member mapping, and report markers have not
been changed. This update supplies implementation evidence against its tasks.
It does not establish when earlier work began or remove the remaining weeks.

## Reliability changes

The controller now attempts emergency cleanup in `finally`. A failed event
write cannot prevent reversal of an active fault. Logging failures are
reported separately from cleanup failures, and a run with an incomplete event
log fails. A controller interrupted by `KeyboardInterrupt` attempts cleanup
before propagating the interruption.

Docker commands now have a 30-second subprocess timeout. If a command fails or
is interrupted before returning a fault handle, netem/process adapters attempt
rollback directly. An interrupted network disconnection attempts to reconnect
every originally attached network. Reconnection continues after an individual
network error so other networks still get a recovery attempt.

The existing baseline configuration/loading, reset configuration/error handling,
client/server behavior, tests, and CI checks remain. CI adds the fault-safety
check and saves its evidence. Scenario version 1.0 and the event field names
remain unchanged. The summary adds `logging_errors`; the integration contract
documents this and the failure-event ordering.

## Measured results

The final safety run took place on November 20, 2026, from 16:20:40 to 16:22:41
UTC on this Windows/Docker Desktop environment. Two trials were run per fault.
Each trial used 8 baseline, 3 during-fault, and 8 recovery requests. All
during-fault samples were checked against the actual event timestamps.

| Fault setting | Observed effect over two trials | Recovery |
| --- | --- | --- |
| 250 ms outgoing delay, no jitter | Mean successful response time was 516.38 and 516.12 ms, versus baseline means of 4.23 and 5.33 ms. All 6 during-fault requests succeeded. | 16/16 requests succeeded. |
| 100% outgoing packet loss | 6/6 during-fault requests failed. | 16/16 succeeded. |
| Full network disconnection | 6/6 during-fault requests failed. | 16/16 succeeded using the normal server name. |
| Process interruption with SIGKILL | 6/6 during-fault requests failed. | 16/16 succeeded after restart. |

Across the normal trials, all 64 baseline and 64 recovery requests succeeded.
Every trial verified cleanup and restored network membership. The additional
controlled interruption cleaned the active delay and passed 8/8 recovery
requests. Its controller summary correctly records a failed experiment, because
the scenario was intentionally interrupted.

The first measurement prototype used the service name during outages. DNS
resolution delayed samples beyond the fault window, so four timing checks
failed even though faults and recovery were observed. The final runner uses
the pre-fault server IP for before/during measurements, then the service name
for recovery. The pilot output is retained as `measurement-pilot.json`, rather
than being relabeled as a successful run.

Two trials and three during-fault samples per trial demonstrate these safety
cases on this machine. They do not establish performance distributions,
25% random-loss behavior, or replay reproducibility. Measured HTTP latency
also must not be treated as the configured delay for a single packet [1].

## Evidence and how to repeat it

- [Raw requests and all trial checks](evidence/fault-safety-2026-11-20/report.json)
- [Compact per-trial results](evidence/fault-safety-2026-11-20/summary.csv)
- [Verification commands, outcomes, and source checksums](evidence/fault-safety-2026-11-20/verification.json)
- The same evidence folder includes all nine scenario/event/summary bundles.
- [Fault-control guide and rehearsal steps](fault-control-guide.md)

Repeat from the repository root with Docker Desktop running:

```powershell
docker compose up -d --build --wait server
docker compose build baseline
python -m pytest -q
python -m faultlab.safety_check --trials 2
python reset.py
```

Verified outcomes: 115 tests passed, 8/8 fault trials passed, the interruption
check passed, and the existing reset printed `RESET PASSED`. These outcomes
refer to local executions; hosted GitHub Actions results must be checked on
the pull request.

## Reliability source review notes

Python documents that `subprocess.run(timeout=...)` kills and waits for its
child on timeout [2]. For FaultLab, that child is the Docker CLI, so its
termination is not proof that the daemon did not already apply the operation.
This is the reason for attempting rollback after uncertain command outcomes.

Docker's reconnect command supports a network alias [3]. FaultLab restores the
`server` alias so normal clients can use the same service address after a
disconnect. Restoration is checked through a new workload using that name.
Netem's egress placement and TCP/timer limitations [1] also support measuring
actual application behavior rather than treating command success as proof of
an observed impairment.

## Remaining work

1. Review this branch with the team and check hosted CI before merging it.
2. Continue the scheduled results analysis with additional latency/loss settings
   and repeated measurements through December 6. Keep the raw results.
3. Check the fault events and summaries with Chidera's recording/replay work
   once that component is integrated. This update does not complete her tasks.
4. Read the sources, review the changed code, and practice the guide. The Gantt
   rehearsal starts November 23 and is not established by automated test results.

## References

[1] S. Hemminger, F. Ludovici, and H. P. Pfeifer, "tc-netem(8)," *Linux manual pages*. [Online]. Available: https://man7.org/linux/man-pages/man8/tc-netem.8.html. [Accessed: Nov. 20, 2026].

[2] Python Software Foundation, "subprocess — Subprocess management," *Python 3.12 documentation*. [Online]. Available: https://docs.python.org/3.12/library/subprocess.html. [Accessed: Nov. 20, 2026].

[3] Docker, Inc., "docker network connect," *Docker Docs*. [Online]. Available: https://docs.docker.com/reference/cli/docker/network/connect/. [Accessed: Nov. 20, 2026].

Prepared and checked with OpenAI Codex assistance on November 20, 2026. The
automated executions above are real. They do not establish student research
hours, independent authorship, or an oral rehearsal. Retain the course-required
assistance disclosure when using this material.
