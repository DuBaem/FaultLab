FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN apt-get update \
    && apt-get install --no-install-recommends -y iproute2 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt

COPY server/server.py .

CMD ["python", "server.py"]
