
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from baseline.baseline import run_request
from faultlab.controller import execute_scenario
from faultlab.fault_adapters import DryRunFaultExecutor, FaultExecutor
from recording.observation_logger import save_observations


def run_experiment(
    scenario,
    server_url,
    request_count=100,
    request_interval=0.2,
    request_timeout=3.0,
    recovery_seconds=4.0,
    results_dir=Path("results/experiments"),
    dry_run=False,
    observation_duration=None,
):
    """
    Run application requests concurrently with a fault scenario.

    If observation_duration is provided, collect requests for
    approximately that many seconds from workload start.

    Otherwise, use the legacy behavior: stop after the
    controller finishes plus the recovery window, or when
    the request limit is reached.
    """

    if request_count < 1:
        raise ValueError("request_count must be at least 1")
    if request_interval < 0:
        raise ValueError("request_interval cannot be negative")
    if request_timeout <= 0:
        raise ValueError("request_timeout must be positive")
    if recovery_seconds < 0:
        raise ValueError("recovery_seconds cannot be negative")
    if observation_duration is not None and observation_duration <= 0:
        raise ValueError("observation_duration must be positive")

    results_dir = Path(results_dir)

    observations = []
    workload_errors = []

    start_signal = threading.Event()
    stop_signal = threading.Event()
    workload_finished = threading.Event()
    controller_finished=threading.Event()
    recovery_deadline = None

    experiment_start = time.perf_counter()

    def workload():
        start_signal.wait()

        try:
            for i in range(request_count):
                if stop_signal.is_set():
                    break

                elapsed = time.perf_counter() - experiment_start

                if observation_duration is not None:
                    minimum_elapsed = elapsed >= observation_duration
                    recovery_complete = (
                        controller_finished.is_set()
                        and recovery_deadline is not None
                        and time.perf_counter() >= recovery_deadline
                    )

                    if minimum_elapsed and recovery_complete:
                        break
                request_id = f"request-{i:04d}"
                started_at = datetime.now(timezone.utc).isoformat()

                try:
                    result = run_request(
                        server_url,
                        request_id,
                        10,
                        request_timeout,
                    )
                except Exception as exc:
                    workload_errors.append(str(exc))
                    break

                finished_at = datetime.now(timezone.utc).isoformat()

                observation = dict(result)
                observation["started_at_utc"] = started_at
                observation["finished_at_utc"] = finished_at
                observation["elapsed_since_start_s"] = round(elapsed, 4)

                observations.append(observation)

                if i < request_count - 1:
                    if stop_signal.wait(request_interval):
                        break

        finally:
            workload_finished.set()

    worker = threading.Thread(target=workload)
    worker.start()

    executor = (
        DryRunFaultExecutor()
        if dry_run
        else FaultExecutor()
    )

    start_signal.set()

    try:
        summary = execute_scenario(
            scenario,
            executor=executor,
            results_dir=results_dir,
            time_scale=0 if dry_run else 1,
        )

        if observation_duration is None:
            workload_finished.wait(timeout=recovery_seconds)
        else:
            recovery_deadline = time.perf_counter() + recovery_seconds
            controller_finished.set()

            workload_finished.wait()

    finally:
        stop_signal.set()
        worker.join()

    run_dir = results_dir / summary["run_id"]

    observation_path = save_observations(
        run_dir,
        observations,
    )

    workload_config = {
        "server_url": server_url,
        "request_count": request_count,
        "request_interval": request_interval,
        "request_timeout": request_timeout,
        "recovery_seconds": recovery_seconds,
        "observation_duration": observation_duration,
        "input_value": 10,
    }

    config_path = run_dir / "workload_config.json"

    config_path.write_text(
        json.dumps(workload_config, indent=2),
        encoding="utf-8",
    )

    return {
        "summary": summary,
        "observation_path": str(observation_path),
        "workload_config_path": str(config_path),
        "request_count": len(observations),
        "workload_errors": workload_errors,
    }
