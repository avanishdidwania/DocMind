# ─── DocMind Production Dockerfile ──────────────────────────────────────────
#
# Key decisions:
# 1. Dependencies before code (Docker layer caching — rebuilds in seconds)
# 2. Non-root user (security — limits blast radius if compromised)
# 3. Health check (orchestrators auto-restart unhealthy containers)
# 4. Slim base image (smaller attack surface, faster pulls)
#

FROM python:3.12-slim

# ─── System dependencies ───────────────────────────────────────────────────
# curl for health check, build-essential for some Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# ─── Working directory ─────────────────────────────────────────────────────
WORKDIR /app

# ─── Dependencies FIRST (Docker layer caching!) ───────────────────────────
# This layer is cached as long as requirements.txt doesn't change.
# Code changes → only layers AFTER this rebuild → seconds, not minutes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─── Application code (changes frequently) ────────────────────────────────
COPY backend/ .

# ─── Non-root user (security) ─────────────────────────────────────────────
# If container is compromised, attacker has limited privileges.
RUN useradd -m -r appuser && chown -R appuser:appuser /app
USER appuser

# ─── Port ──────────────────────────────────────────────────────────────────
EXPOSE 8000

# ─── Health check ──────────────────────────────────────────────────────────
# Docker/Kubernetes uses this to detect unhealthy containers and restart them.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# ─── Run ───────────────────────────────────────────────────────────────────
# Production: multiple workers, no reload
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
