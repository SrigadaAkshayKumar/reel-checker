# API and worker image (same image, different command). Build context: the repo root.
#   docker build -f backend/Dockerfile -t reel-checker-api .
# Works on x86-64 and ARM64 (Oracle Ampere A1).
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/var/lib/reel-checker \
    OUTPUT_DIR=/var/lib/reel-checker/output

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/reel/backend
COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY backend/run.py .
COPY data/seed /srv/reel/data/seed

RUN useradd --system --uid 10001 --home-dir /var/lib/reel-checker reel \
 && mkdir -p /var/lib/reel-checker \
 && chown reel:reel /var/lib/reel-checker
USER reel
VOLUME /var/lib/reel-checker
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

# No access log: it would record uploaders' IP addresses (privacy rules in docs/workflow.md).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
