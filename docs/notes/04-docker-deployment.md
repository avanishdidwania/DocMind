# 04 - Docker & Deployment

## What Docker Is

Docker packages your application + all its dependencies into a **container** — a lightweight, isolated environment that runs identically everywhere (your laptop, CI/CD, production server).

"But it works on my machine" → "It works in the container, which runs the same everywhere."

## Why Docker for LLM APIs

- **Reproducibility** — exact same Python version, exact same packages, everywhere
- **Isolation** — your app doesn't conflict with other services on the same machine
- **Deployment** — push a container image, pull it anywhere, run it
- **Scaling** — Kubernetes runs multiple copies of your container behind a load balancer

## Dockerfile — Key Decisions

```dockerfile
# 1. Base image — slim for smaller size
FROM python:3.12-slim

# 2. Working directory
WORKDIR /app

# 3. Dependencies FIRST (Docker layer caching!)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Application code SECOND (changes frequently)
COPY . .

# 5. Non-root user (security)
RUN useradd -m appuser
USER appuser

# 6. Health check (container orchestration)
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 7. Expose port
EXPOSE 8000

# 8. Run command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Decision 1: Dependencies Before Code (Layer Caching)

**The problem:** `pip install` takes 2-5 minutes. If you copy ALL files first, then install, Docker re-installs everything on every code change.

**The solution:** Docker caches layers. If a layer's input hasn't changed, it reuses the cached result.

```
Layer 1: COPY requirements.txt .    ← rarely changes
Layer 2: RUN pip install ...         ← cached if requirements.txt unchanged
Layer 3: COPY . .                    ← changes on every code edit
```

Result: code-only changes rebuild in seconds, not minutes.

### Decision 2: Non-Root User

**The risk:** If your container is compromised (e.g., code execution vulnerability), an attacker running as root inside the container could potentially escape to the host.

**The fix:** Create a non-root user, switch to it. The app runs with minimal privileges.

### Decision 3: Health Check

**Why:** Container orchestrators (Docker Compose, Kubernetes, Render) need to know if your app is healthy. If the health check fails, they:
- Stop sending traffic to that container
- Restart it automatically
- Spin up a replacement

Without a health check, a crashed app stays in the rotation, serving 500 errors.

## Building & Running

```bash
# Build the image
docker build -t docmind-api .

# Run the container
docker run -p 8000:8000 --env-file .env docmind-api

# Run with docker-compose (multi-container)
docker compose up
```

## Deployment on Render

Render is a cloud platform that can build and host Docker containers.

**render.yaml** — tells Render how to build and run your service:

```yaml
services:
  - type: web
    name: docmind-api
    runtime: docker
    envVars:
      - key: GOOGLE_API_KEY
        sync: false  # Set manually in Render dashboard
      - key: LANGSMITH_API_KEY
        sync: false
```

**How it works:**
1. Push code to GitHub
2. Render detects the push, builds your Docker image
3. Deploys the container with your env vars
4. Routes traffic to it with HTTPS

## Production vs Demo (Key Differences)

| Concern | Demo/Local | Production |
|---------|-----------|------------|
| Workers | 1 (uvicorn --reload) | Multiple (uvicorn --workers 4) |
| Restart | Manual | Auto (health check + orchestrator) |
| Secrets | .env file | Vault / Render env vars / AWS Secrets Manager |
| Logs | stdout/console | Shipped to ELK/Datadog/CloudWatch |
| SSL | None (http://localhost) | Automatic HTTPS (Render/AWS handles it) |
| Scaling | Single container | Multiple containers + load balancer |

## Docker Layer Caching — Visual Explanation

```
First build:
  Layer 1: FROM python:3.12-slim       [downloads base image ~150MB]
  Layer 2: COPY requirements.txt       [copies 1 file]
  Layer 3: pip install                  [installs deps ~3 minutes]
  Layer 4: COPY . .                    [copies your code]
  Layer 5: CMD uvicorn...              [sets run command]
  Total: ~4 minutes

Second build (only code changed):
  Layer 1: FROM python:3.12-slim       [CACHED ✓]
  Layer 2: COPY requirements.txt       [CACHED ✓] (file didn't change)
  Layer 3: pip install                  [CACHED ✓] (requirements.txt unchanged)
  Layer 4: COPY . .                    [REBUILDS] (code changed)
  Layer 5: CMD uvicorn...              [REBUILDS] (downstream of changed layer)
  Total: ~10 seconds
```

## Interview Questions

**Q: Why Docker for an AI/LLM API?**
A: Reproducibility and deployment simplicity. LLM APIs have complex dependencies (specific Python versions, ML libraries, system packages). Docker ensures the exact same environment runs locally, in CI/CD, and in production. It also enables horizontal scaling — run N identical containers behind a load balancer.

**Q: Explain Docker layer caching and why it matters for your build.**
A: Docker caches each layer. If a layer's input hasn't changed, it reuses the cached result. We copy `requirements.txt` and install dependencies BEFORE copying application code. Since dependencies change rarely but code changes every commit, this means most builds skip the expensive pip install step. Rebuilds go from 5 minutes to 10 seconds.

**Q: Why run as non-root in the container?**
A: Principle of least privilege. If the application has a code execution vulnerability, an attacker gains the privileges of the container user. Running as root means they could potentially escape to the host or access sensitive files. Non-root limits the blast radius of a compromise.

**Q: How does the health check work?**
A: The Dockerfile defines a HEALTHCHECK that periodically hits our `/health` endpoint. If it fails N times consecutively, the container is marked unhealthy. The orchestrator (Kubernetes, Render, ECS) then stops routing traffic to it and spins up a replacement. This gives us self-healing — crashed services recover automatically.

**Q: How would you scale this API?**
A: Horizontally. Run multiple container instances behind a load balancer. Key requirement: no in-process state. Our cache, rate limiter, and metrics all need to move to external services (Redis, Prometheus) so all instances share the same data. The application code itself doesn't change — we just swap backends.

**Q: What's the difference between `--reload` and `--workers`?**
A: `--reload` watches for file changes and restarts — development only (single process, slow restart). `--workers 4` runs 4 separate processes handling requests in parallel — production mode. Never use `--reload` in production (it's slow and unnecessary).
