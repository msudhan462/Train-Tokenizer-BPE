FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

# Puts src/ on the module search path so every stage can do `import config`.
ENV PYTHONPATH=/app/src

# Each Batch job definition specifies which script to run as the command.
# e.g. ["python", "-u", "src/01_ingest/download.py"]
ENTRYPOINT ["python", "-u"]
