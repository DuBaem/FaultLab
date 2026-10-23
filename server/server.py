from flask import Flask, jsonify, request

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify({"status": "healthy"}), 200


@app.post("/process")
def process():
    # silent=True so a missing/malformed body gives us None instead of raising
    # Flask's own HTML error page before we get a chance to respond with JSON.
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "status": "error",
            "message": "a JSON object body is required"
        }), 400

    request_id = data.get("request_id")
    value = data.get("value")

    if request_id is None or value is None:
        return jsonify({
            "status": "error",
            "message": "request_id and value are required"
        }), 400

    # bool is technically an int in Python, so it needs its own check here,
    # otherwise True/False would quietly pass as a valid numeric value.
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return jsonify({
            "status": "error",
            "message": "value must be a number"
        }), 400

    return jsonify({
        "request_id": request_id,
        "status": "success",
        "result": value * 2
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)