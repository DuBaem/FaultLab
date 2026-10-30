import pytest

import server


@pytest.fixture
def client():
    server.app.config["TESTING"] = True
    with server.app.test_client() as test_client:
        yield test_client


def test_health_returns_200_and_healthy_status(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "healthy"}


def test_valid_process_request_succeeds(client):
    response = client.post("/process", json={"request_id": "req-001", "value": 10})

    assert response.status_code == 200
    assert response.get_json() == {"request_id": "req-001", "status": "success", "result": 20}


def test_missing_body_returns_clean_json_400(client):
    # No json= and no data= at all - an empty POST with no body.
    response = client.post("/process")

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"


def test_malformed_json_returns_clean_json_400(client):
    response = client.post(
        "/process",
        data="{not valid json",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"


def test_missing_request_id_returns_400(client):
    response = client.post("/process", json={"value": 10})

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"


def test_missing_value_returns_400(client):
    response = client.post("/process", json={"request_id": "req-001"})

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"


def test_string_value_returns_400(client):
    response = client.post("/process", json={"request_id": "req-001", "value": "ten"})

    assert response.status_code == 400


def test_list_value_returns_400(client):
    response = client.post("/process", json={"request_id": "req-001", "value": [1, 2]})

    assert response.status_code == 400


def test_bool_value_returns_400(client):
    # bool is a subclass of int in Python, so this needs its own explicit check
    # in the server - otherwise True*2 would quietly pass as a valid number.
    response = client.post("/process", json={"request_id": "req-001", "value": True})

    assert response.status_code == 400


@pytest.mark.parametrize("value,expected_result", [(10, 20), (0, 0), (-5, -10), (2.5, 5.0)])
def test_valid_numeric_values_return_doubled_result(client, value, expected_result):
    response = client.post("/process", json={"request_id": "req-001", "value": value})

    assert response.status_code == 200
    assert response.get_json()["result"] == expected_result
