FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
# Tell Python to find first-party packages relative to /app so imports
# like `from api.main import app` keep working regardless of where the
# container is executed from.
ENV PYTHONPATH=/app

WORKDIR /app

# Build deps for any wheels that don't have pre-built versions on this
# slim base (pymupdf, faiss-cpu, etc. ship wheels for linux/amd64, but
# we keep the toolchain available so a stale requirement doesn't break
# the build). They're removed after pip install in a single layer to
# keep the image small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Healthcheck against the FastAPI /health endpoint so Cloud Run can
# decide whether a freshly-started container is ready to receive
# traffic. The 30s start-period covers slow Firebase/Groq client init.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+__import__('os').environ.get('PORT','8080')+'/health',timeout=3).status==200 else 1)"

# `--workers 1` keeps memory low on a small Cloud Run instance; raise
# only if the instance has the headroom (each worker re-initialises
# Firebase, Groq, and the LLM clients).
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips=*"]
