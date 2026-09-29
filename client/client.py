import os
import requests

BASE_URL = os.getenv("SERVER_URL", "http://127.0.0.1:5000")

health_response = requests.get(f"{BASE_URL}/health")
print("Health:", health_response.json())

payload = {
    "request_id": "req-001",
    "value": 10
}

process_response = requests.post(
    f"{BASE_URL}/process",
    json=payload
)

print("Process:", process_response.json())