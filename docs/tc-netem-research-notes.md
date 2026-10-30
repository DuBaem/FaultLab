# `tc/netem` Research and Safe Prototype Notes

**Prepared:** October 22, 2026

**Scope:** FaultLab local Docker fault injection

AI-assistance disclosure: these notes were researched and drafted with OpenAI
Codex on October 22, 2026. They are supporting research, not an original student
artifact. Fidel must read the cited sources, verify the conclusions, revise the
notes in his own words, and document the assistance before claiming research
time or discussing the material in a report meeting.

## Research Question

How can FaultLab apply repeatable latency, packet-loss, disconnection, and
process faults to a Docker client/server system while limiting privileges and
guaranteeing a recoverable state?

## Findings

Linux `netem` is a queue discipline used to emulate network properties on live
packets. Its supported controls include delay, jitter, random loss,
corruption, duplication, and reordering [1]. FaultLab version 1.0 uses only
delay and random loss because those are the two network faults committed to in
the formal proposal and Gantt chart.

The selected commands operate on traffic leaving the server's `eth0`
interface. Applying the rule to the server is useful for this client/server
prototype because delayed or dropped responses are directly visible to the
baseline workload. The Linux documentation warns that timer granularity and
TCP queue behavior can affect measured results [1]. Therefore, the scenario
file describes the requested impairment, while the experiment output records
the observed timing rather than claiming that configured and measured values
are identical.

An empirical evaluation by Jurgelionis et al. found that NetEm generally
matched expected delay and uncorrelated packet-loss behavior, but realized
jitter could be lower than the configured input [2]. This influenced two
FaultLab choices: jitter is optional, and the event bundle stores planned and
observed times for later comparison. Hemminger's earlier NetEm work also
motivates using network emulation to expose applications to realistic delay
and loss without requiring a physical wide-area test network [3].

Changing a container's traffic-control configuration requires a Linux network
administration capability. Docker Compose supports adding a specific
capability with `cap_add` [4]. FaultLab grants only `NET_ADMIN` to the local
server container instead of using a privileged container or adding all
capabilities. Scenario values remain data: they are validated and passed as
separate subprocess arguments, and scenario files cannot supply commands.

For a complete temporary disconnection, Docker provides explicit network
disconnect and connect operations [5], [6]. FaultLab records the server's
attached network names before isolation and restores the Compose service-name
alias during reconnection. Process failure is handled separately by sending an
allowlisted `SIGTERM` or `SIGKILL`, waiting for the declared duration, starting
the service, and waiting for its health state.

## Safety Decisions Applied to the Prototype

1. Only the local, long-running Compose `server` is accepted as a version 1.0
   fault target.
2. Raw shell commands and arbitrary executable names are rejected.
3. Latency is limited to 1-5000 ms; jitter is limited to 0-1000 ms.
4. Packet loss is limited to 0.1-100 percent.
5. Each action and the complete scenario have bounded durations.
6. Version 1.0 rejects overlapping faults so cleanup is deterministic.
7. Every successful application receives a matching cleanup attempt.
8. Network cleanup runs `tc qdisc del` and then checks that `netem` is absent.
9. Process cleanup restarts the service and waits for a healthy/running state.
10. `reset.py` recreates the server and independently verifies health,
    processing behavior, and absence of an active `netem` qdisc.

## Limitations and Next Evaluation

- NetEm affects egress traffic on the selected interface; results should not be
  generalized to every possible ingress or router placement.
- Docker Desktop adds a virtualization layer on Windows, so observed timing may
  include host scheduling and virtualization effects.
- Random packet loss will vary between runs unless a supported deterministic
  seed strategy is added and evaluated.
- Unit tests verify validation, command construction, scheduling, event output,
  and cleanup paths. A live Docker run is still required to measure actual
  latency, request failures, and post-reset recovery on the demonstration
  machine.

## References

[1] S. Hemminger, F. Ludovici, and H. P. Pfeifer, "tc-netem(8) - Linux manual
page," *Linux man-pages project*. [Online]. Available:
https://man7.org/linux/man-pages/man8/tc-netem.8.html. [Accessed: Oct. 22,
2026].

[2] A. Jurgelionis, J.-P. Laulajainen, M. Hirvonen, and A. I. Wang, "An
empirical study of NetEm network emulation functionalities," in *Proc. 20th
Int. Conf. Computer Communications and Networks (ICCCN)*, Maui, HI, USA, 2011,
pp. 1-6, doi: 10.1109/ICCCN.2011.6005933.

[3] S. Hemminger, "Network emulation with NetEm," in *Proc. Australia's 6th
National Linux Conf.*, Canberra, Australia, Apr. 2005. [Online]. Available:
https://citeseerx.ist.psu.edu/document?doi=9180aa7b7978c62363e4af3a9053371775fbcbdc

[4] Docker, Inc., "Services top-level elements: cap_add," *Docker Docs*.
[Online]. Available: https://docs.docker.com/reference/compose-file/services/
[Accessed: Oct. 22, 2026].

[5] Docker, Inc., "docker network disconnect," *Docker Docs*. [Online].
Available: https://docs.docker.com/reference/cli/docker/network/disconnect/
[Accessed: Oct. 22, 2026].

[6] Docker, Inc., "docker network," *Docker Docs*. [Online]. Available:
https://docs.docker.com/reference/cli/docker/network/ [Accessed: Oct. 22,
2026].
