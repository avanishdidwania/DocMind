# 02 - FastAPI Fundamentals

## What It Is

FastAPI is a modern Python web framework for building APIs. It's async-first, uses Python type hints for automatic validation, and auto-generates interactive API docs (Swagger UI at `/docs`).

## Why FastAPI (Not Flask, Not Django)

| | FastAPI | Flask | Django |
|--|---------|-------|--------|
| Async | Native (async/await) | Needs workarounds | Limited |
| Performance | Very fast (built on Starlette) | Slower | Slower |
| Type safety | Built-in (Pydantic) | Manual | Partial |
| API docs | Auto-generated | Manual (Swagger plugin) | Manual |
| Learning curve | Low | Low | High |
| Use case | APIs, microservices | Small apps, APIs | Full web apps with ORM |

**Interview answer:** "FastAPI is ideal for LLM/AI backends because it's async-native (LLM calls are I/O-bound, async lets us handle many concurrent requests), has built-in Pydantic validation (we validate every request and response automatically), and auto-generates OpenAPI docs so frontend teams always have an up-to-date API reference."

## Key Concepts

### Lifespan (Modern Startup/Shutdown)

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP — runs once when app starts
    app.state.agent = ProductionAgent(settings)
    app.state.cache = Cache(settings)
    app.state.metrics = MetricsCollector()
    print("All components initialized")
    
    yield  # App is running, handling requests
    
    # SHUTDOWN — runs when app stops
    app.state.metrics.log_summary()
    print("Shutdown complete")

app = FastAPI(lifespan=lifespan)
```

**Why not `@app.on_event("startup")`?**
- `on_event` is deprecated
- Lifespan is a context manager — guarantees cleanup even if startup partially fails
- Cleaner pattern — startup and shutdown logic in one place

### app.state — Sharing Components Across Requests

Components created at startup live on `app.state`. Every request handler can access them without re-creating:

```python
@app.post("/chat")
async def chat(request: Request):
    agent = request.app.state.agent  # Created once at startup
    cache = request.app.state.cache  # Not re-created per request
    # ... use them
```

**Why this matters:** Creating an LLM client, loading models, connecting to DBs — these are expensive. Do it once, share everywhere.

### Pydantic Models for Request/Response

```python
from pydantic import BaseModel

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None

class ChatResponse(BaseModel):
    response: str
    cached: bool
    model_used: str
    latency_ms: float

class HealthResponse(BaseModel):
    status: str
    uptime: float
    version: str

class StandardErrorResponse(BaseModel):
    error: str
    detail: str | None = None
    request_id: str
```

**What Pydantic gives you:**
- Automatic request validation (wrong type? missing field? → 422 error automatically)
- Response serialization (your Python objects → JSON automatically)
- API documentation (Swagger UI shows all fields, types, examples)
- IDE autocomplete (type hints everywhere)

### Dependency Injection

FastAPI's `Depends()` lets you inject shared logic into route handlers:

```python
from fastapi import Depends

async def get_current_user(token: str = Header(...)):
    # Validate token, return user
    return user

@app.post("/chat")
async def chat(request: ChatRequest, user = Depends(get_current_user)):
    # user is automatically resolved
    pass
```

**Use cases:** Auth, DB sessions, rate limit checks, logging context.

### Uvicorn — The ASGI Server

FastAPI is just the framework. Uvicorn actually runs it and handles HTTP:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

- `main:app` — module:variable (the FastAPI instance)
- `--reload` — auto-restart on code changes (dev only, never in production)
- `--host 0.0.0.0` — listen on all interfaces (needed for Docker)
- In production: `uvicorn main:app --workers 4` (multiple worker processes)

## pydantic-settings for Configuration

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # These auto-load from environment variables
    primary_model: str = "gemini-2.0-flash"
    fallback_model: str = "gemini-1.5-pro"
    google_api_key: str  # Required — app won't start without it
    rate_limit: str = "10/minute"
    cache_ttl: int = 3600
    langsmith_tracing: bool = True
    
    class Config:
        env_file = ".env"
```

**Why over python-dotenv:**
- Typed (int, bool, str — not everything is a string)
- Validated at startup (missing required var → immediate error, not runtime crash)
- Defaults built-in
- IDE autocomplete for `settings.primary_model`

## Interview Questions

**Q: Why async for an LLM API?**
A: LLM calls are I/O-bound (waiting for the model to respond, 1-5 seconds). With sync code, one request blocks the entire thread. With async, while waiting for the LLM response, the server can handle other incoming requests. This dramatically improves throughput under concurrent load.

**Q: What's the difference between Uvicorn and FastAPI?**
A: FastAPI is the web framework (routing, validation, serialization). Uvicorn is the ASGI server that actually handles HTTP connections and passes requests to FastAPI. Similar to how Flask needs Gunicorn, FastAPI needs Uvicorn. In production you'd run multiple Uvicorn workers for parallelism.

**Q: How do you handle errors in FastAPI?**
A: Exception handlers + Pydantic validation. FastAPI auto-returns 422 for invalid requests. For business logic errors, we use custom exception handlers that return our StandardErrorResponse format. The client always gets a consistent JSON error shape, never a raw stack trace.

**Q: How do you share expensive resources across requests?**
A: FastAPI's lifespan pattern. We create expensive objects (DB connections, LLM clients, model instances) once at startup and store them on `app.state`. Every request handler accesses them via `request.app.state.component`. No per-request initialization overhead.
