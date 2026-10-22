from unittest.mock import patch, MagicMock

import pytest
import requests

import baseline


def make_response(status_code, body):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = body
    return response


def test_calculate_summary_all_success():
    results = [
        {"success": True, "latency_ms": 10.0},
        {"success": True, "latency_ms": 20.0},
        {"success": True, "latency_ms": 30.0},
    ]
    summary = baseline.calculate_summary(results)

    assert summary["total_requests"] == 3
    assert summary["successful_requests"] == 3
    assert summary["failed_requests"] == 0
    assert summary["success_rate"] == 100.0
    assert summary["latency_ms"]["min"] == 10.0
    assert summary["latency_ms"]["max"] == 30.0
    assert summary["latency_ms"]["mean"] == 20.0
    assert summary["latency_ms"]["median"] == 20.0
    assert summary["latency_ms"]["stddev"] is not None


def test_calculate_summary_mixed_success_and_failure():
    results = [
        {"success": True, "latency_ms": 5.0},
        {"success": False, "latency_ms": None},
        {"success": True, "latency_ms": 15.0},
    ]
    summary = baseline.calculate_summary(results)

    assert summary["total_requests"] == 3
    assert summary["successful_requests"] == 2
    assert summary["failed_requests"] == 1
    # Failures shouldn't skew the latency numbers, which only cover successful requests.
    assert summary["success_rate"] == pytest.approx(66.666, abs=0.01)
    assert summary["latency_ms"]["mean"] == 10.0


def test_calculate_summary_single_data_point_has_no_stddev():
    results = [{"success": True, "latency_ms": 12.0}]
    summary = baseline.calculate_summary(results)

    # Standard deviation needs at least two values to be meaningful.
    assert summary["latency_ms"]["stddev"] is None


def test_calculate_summary_empty_results():
    summary = baseline.calculate_summary([])

    assert summary["total_requests"] == 0
    assert summary["success_rate"] == 0
    assert summary["latency_ms"]["mean"] is None


def test_run_request_marks_success_when_response_matches():
    response = make_response(200, {"request_id": "r1", "status": "success", "result": 20})
    with patch.object(baseline.requests, "post", return_value=response):
        result = baseline.run_request("http://server", "r1", 10, 3)

    assert result["success"] is True
    assert result["observed_result"] == 20
    assert result["error"] is None


def test_run_request_fails_on_wrong_result():
    # Server claims success but returns the wrong value - should not count as a pass.
    response = make_response(200, {"request_id": "r1", "status": "success", "result": 999})
    with patch.object(baseline.requests, "post", return_value=response):
        result = baseline.run_request("http://server", "r1", 10, 3)

    assert result["success"] is False
    assert result["observed_result"] == 999


def test_run_request_fails_on_mismatched_request_id():
    response = make_response(
        200,
        {"request_id": "different-id", "status": "success", "result": 20},
    )
    with patch.object(baseline.requests, "post", return_value=response):
        result = baseline.run_request("http://server", "r1", 10, 3)

    assert result["success"] is False


def test_run_request_fails_on_non_200_status():
    response = make_response(500, {"status": "error"})
    with patch.object(baseline.requests, "post", return_value=response):
        result = baseline.run_request("http://server", "r1", 10, 3)

    assert result["success"] is False
    assert result["http_status"] == 500


def test_run_request_records_timeout_instead_of_raising():
    with patch.object(baseline.requests, "post", side_effect=requests.Timeout("timed out")):
        result = baseline.run_request("http://server", "r1", 10, 3)

    assert result["success"] is False
    assert "timed out" in result["error"]


def test_main_waits_between_requests_when_interval_is_configured(monkeypatch):
    monkeypatch.setattr(baseline, "BASELINE_REQUESTS", 2)
    monkeypatch.setattr(baseline, "REQUEST_INTERVAL_SECONDS", 0.25)
    monkeypatch.setattr(baseline, "wait_for_health", lambda *_args: True)
    monkeypatch.setattr(
        baseline,
        "save_results",
        lambda *_args: baseline.Path("results/test-baseline.json"),
    )
    monkeypatch.setattr(
        baseline,
        "run_request",
        lambda *_args: {"success": True, "latency_ms": 10.0},
    )

    with patch.object(baseline.time, "sleep") as sleep:
        baseline.main()

    sleep.assert_called_once_with(0.25)
