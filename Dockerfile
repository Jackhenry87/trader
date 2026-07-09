# Insider-copy paper trading bot — slim, single-stage image.
FROM python:3.11-slim

# Don't buffer stdout (structured logs should stream) and don't write .pyc.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY config ./config
COPY src ./src
COPY backtest ./backtest

RUN pip install --upgrade pip && pip install .

# Persistent SQLite state lives here; mount a volume to survive restarts.
RUN mkdir -p /app/data
VOLUME ["/app/data"]

# Default: start the scheduler. DRY_RUN and the paper gate are read from env.
# Nothing places a live order without ALLOW_LIVE=true AND CONFIRM_LIVE=true.
ENTRYPOINT ["python", "-m", "src.main"]
CMD ["run"]
