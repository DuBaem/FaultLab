# My fault-control update · November 20, 2026

**Fidel Anyanwu · Scenario control and fault injection**

My part of FaultLab is making sure the server recovers when a fault ends, including when someone stops an experiment halfway through. The four fault types and the controller reached `main` in [PR #3](https://github.com/DuBaem/FaultLab/pull/3). This week I used OpenAI Codex to help change the cleanup code and run the checks in [PR #7](https://github.com/DuBaem/FaultLab/pull/7). The most useful case for our demo is the interrupted run. The experiment stopped early, the controller removed the delay, and the server answered all eight follow-up requests.

## Where my work stands

These are the planned dates for member 2 in `FaultLab_Gantt_Report2_Revised.xlsx`. The last column describes what the team can check as of November 20.

| My Gantt task | Planned dates | What I can show the team |
| --- | --- | --- |
| Fault interfaces, four adapters, validator, and controller | Aug. 31–Oct. 25 | PR #3 includes the working controller and all four fault types. |
| Integration and regression tests | Oct. 19–Nov. 8 | The new cleanup tests run alongside the baseline, reset, client, and server tests. |
| Reliability research and fault safety checks | Nov. 2–22 | The branch adds 22 tests. The Docker run covers eight regular trials and one interrupted run. I still need to review the sources and code myself. |
| Compare fault results | Nov. 16–Dec. 6 | I have two trials per fault to start from. More repetitions and lower packet-loss settings are still ahead. |
| Fault-control guide and demo rehearsal | Nov. 23–Dec. 13 | The [guide](fault-control-guide.md) is ready. My rehearsal is still ahead. |

## What changed in the controller

One bug could leave a delay active if the controller failed to write the next event to disk. Cleanup now runs in Python's `finally` block, so the controller tries to undo the fault even if writing the log fails. The run summary distinguishes errors writing events from errors removing the fault.

The other tricky case is a Docker command that times out or gets interrupted. Python can stop the command-line process [2], but Docker may already have changed the container. The adapter now tries to undo that change. After an interrupted disconnect, it tries every original network even if one reconnect attempt fails. Restoring the `server` alias matters because that's the name the client uses [3].

## What the trials showed

The run lasted from 16:20:40 to 16:22:41 UTC on November 20 using Windows and Docker Desktop. Each trial sent eight requests before the fault, three while it was active, and eight after cleanup. The runner checked each during-fault request against the timestamps in the controller log.

| Fault tested twice | What happened during the fault | After cleanup |
| --- | --- | --- |
| 250 ms outgoing delay, no jitter | In trial 1, the mean rose from 4.23 ms to 516.38 ms. In trial 2 it went from 5.33 ms to 516.12 ms. All six requests succeeded. | 16 of 16 succeeded. |
| 100% outgoing packet loss | All six requests failed. | 16 of 16 succeeded. |
| Full network disconnect | All six requests failed. | 16 of 16 succeeded using the usual server name. |
| Server stopped with `SIGKILL` | All six requests failed. | 16 of 16 succeeded after restart. |

The delay setting applies to packets leaving the server. The client measures the whole HTTP exchange, which helps explain why the times in the table differ from the configured 250 ms [1]. These trials show what happened on this machine. Two trials per fault leave open how much the timing varies, how the workload behaves at partial loss, and how closely a replay matches an original run.

**Why the pilot is still in the evidence folder.** The first version used the Docker service name during outages. DNS lookups took long enough that four timing checks missed the fault window. The updated probe uses the server's IP during the fault and its normal name after cleanup. The [pilot report](evidence/fault-safety-2026-11-20/measurement-pilot.json) preserves those four failures so we can explain why the measurement changed.

## Files behind the results

- [Trial table](evidence/fault-safety-2026-11-20/summary.csv) — the quickest way to compare the eight runs.
- [Full report](evidence/fault-safety-2026-11-20/report.json) — individual requests, pass criteria, and the interruption result. All 64 baseline and 64 recovery requests in the regular trials succeeded.
- [Regular run logs](evidence/fault-safety-2026-11-20/runs/) and [interrupted run log](evidence/fault-safety-2026-11-20/interrupted/) — use the run ID to find the scenario, event sequence, and summary.
- [Verification record](evidence/fault-safety-2026-11-20/verification.json) — commands, results, and source checksums for the version tested in [commit 723992e](https://github.com/DuBaem/FaultLab/commit/723992ec6d657baae99d367381decf7d29cdb2fe). All 115 tests passed, the eight trials and interruption check passed, and reset printed `RESET PASSED`.

OpenAI Codex executed the automated checks. To repeat them, follow the [setup instructions](../README.md), run `python -m pytest -q`, then `python -m faultlab.safety_check --trials 2`, and finally `python reset.py`.

## What I still need to do

I'll review the changes with Dubem and Chidera, compare additional latency and loss settings, and check that Chidera's recorder can match its observations to the fault events. For rehearsal, I want to explain from one run why a failed scenario can still leave the server healthy. My own source review, practice, and research hours are separate from the automated results above.

## References

[1] S. Hemminger, F. Ludovici, and H. P. Pfeifer, "tc-netem(8)," *Linux manual pages*. [Online]. Available: https://man7.org/linux/man-pages/man8/tc-netem.8.html. [Accessed: Nov. 20, 2026].

[2] Python Software Foundation, "subprocess — Subprocess management," *Python 3.12 documentation*. [Online]. Available: https://docs.python.org/3.12/library/subprocess.html. [Accessed: Nov. 20, 2026].

[3] Docker, Inc., "docker network connect," *Docker Docs*. [Online]. Available: https://docs.docker.com/reference/cli/docker/network/connect/. [Accessed: Nov. 20, 2026].
