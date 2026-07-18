FROM python:3.11.15-slim-bookworm@sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PROOFFORGE_DATA_DIR=/app/data

WORKDIR /app
COPY requirements-lock.txt ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-lock.txt
COPY proofforge ./proofforge
COPY static ./static
RUN useradd --create-home --uid 10001 proofforge \
    && mkdir -p /app/data \
    && chown -R proofforge:proofforge /app

USER proofforge

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
CMD ["uvicorn", "proofforge.main:app", "--host", "0.0.0.0", "--port", "8000"]
