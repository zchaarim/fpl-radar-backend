FROM python:3.15-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md constraints.txt ./
COPY src ./src
COPY data/mappings ./data/mappings

# Non-editable install, then drop pip. pip 26.2 ships pip/_vendor/bom.cdx.json
# (setuptools 70.3.0, msgpack 1.1.2, urllib3 2.7.0) that Trivy treats as installed.
RUN pip install --no-cache-dir -c constraints.txt . \
    && pip uninstall -y pip setuptools wheel \
    && mkdir -p /app/data/cache /app/data/understat

ENV FPL_DATA_DIR=/app/data
ENV PORT=8000
ENV FPL_SYNC_INTERVAL_SECONDS=3600

EXPOSE 8000

# /docs is always cheap; /v1/status builds ModelContext on a cold cache.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/docs" >/dev/null || exit 1

CMD ["python", "-m", "fpl_radar.api"]
