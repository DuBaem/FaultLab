from flask import Flask, jsonify, request

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify({"status": "healthy"}), 200


@app.post("/process")
def process():
    data = request.get_json()

    request_id = data.get("request_id")
    value = data.get("value")

    if request_id is None or value is None:
        return jsonify({
            "status": "error",
            "message": "request_id and value are required"
        }), 400

    return jsonify({
        "request_id": request_id,
        "status": "success",
        "result": value * 2
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)