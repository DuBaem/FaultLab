# Why FaultLab delays packets at the server

Prototype notes from October 22, 2026. The server doubles the value in each valid request. That gives us a simple way to tell whether slowing down its network changes the client's response time, whether a request fails altogether, and whether the same workload works again after cleanup.

## Why use Linux netem?

The proposal calls for network delay and packet loss. Linux already provides both through `netem`, a queue that changes how packets leave an interface [1]. Hemminger describes using network emulation to study such conditions without a physical wide-area network [3]. For FaultLab, putting the rule on the test server's `eth0` lets us use the same client, server, and request before and during an experiment.

There are two different measurements here. The scenario specifies what the queue should do to an outgoing packet. The client measures how long it takes to get an answer. TCP behavior and Linux timer resolution can affect that time [1]. Jurgelionis and colleagues found that delay and uncorrelated loss generally followed the configured settings in their tests, while the variation in delay could be smaller than requested [2]. That's why jitter is optional in our scenario and why the controller records planned and observed times separately.

## How the design limits each fault

| Design choice | Why it matters for FaultLab |
| --- | --- |
| Give the local server the additional `NET_ADMIN` capability through Compose's `cap_add` [4]. | The server can use traffic control on its own interface. The other services keep their usual permissions. |
| Accept only the local Compose `server` and validate scenario values before building Docker arguments. | A scenario file can name an approved fault and its settings. It has no field for a shell command or executable. |
| Limit delay to 1–5,000 ms, jitter to 0–1,000 ms, and loss to 0.1–100%. | The validator rejects values outside the experiment's supported range. |
| Bound the total duration and run one action at a time. | The controller has time to remove one rule before another action needs the same interface. |
| After a network fault, remove the queue and inspect `eth0`. | A successful cleanup should leave no active `netem` rule. |

A full disconnect is a different experiment. Docker lets the controller detach the server from its networks, then reconnect it with its service name [5], [6]. For a process fault, the controller sends the allowed `SIGTERM` or `SIGKILL` signal, waits for the scenario duration, then starts the service and checks its state. Both cases can look like an outage to the client. Their cleanup steps differ because one removes a route and the other stops a process.

## What still needs a live check

A unit test can check that the controller schedules the right action and attempts cleanup. To see what a client actually experiences, run the workload in Docker and inspect the requests before, during, and after the fault. The reset script provides a separate check by rebuilding the server, testing both endpoints, and checking the queue.

Results depend on where the rule is applied, how TCP responds, and how Docker Desktop schedules work on the host. Partial packet loss also varies from run to run. Keep the settings with the measurements when comparing trials. For a later example, see the [November 20 results](fidel-progress-2026-11-20.md).

OpenAI Codex helped research and draft these notes on October 22 and edit the wording on November 20. They are supporting material. For the course, personal research credit requires reading the sources, verifying the conclusions, revising the notes, and documenting that assistance.

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
