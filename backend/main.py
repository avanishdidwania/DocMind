"""
DocMind API — FastAPI entry point.

This file JOINS EVERYTHING TOGETHER:
- Lifespan: creates all components at startup, logs summary at shutdown
- Rate limiter: slowapi tracking requests per IP
- CORS: allows frontend to call the API
- Routers: mounts all endpoint groups

Components live on app.state — created ONCE, shared across ALL requests.
"""

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import settings
from agent.graph import ProductionAgent
from middleware.security import SecurityPipeline
from middleware.cache import ResponseCache
from middleware.monitoring import setup_logger, MetricsCollector
from db.vector_store import VectorStore
from services.document_service import DocumentService
from services.retrieval_service import RetrievalService
from services.memory_service import MemoryService
from services.compression_service import CompressionService
from services.evaluation_service import EvaluationService
from api.routes.chat import router as chat_router
from api.routes.health import router as health_router
from api.routes.documents import router as documents_router
from api.routes.stream import router as stream_router
from api.routes.evaluate import router as evaluate_router


# ─── Lifespan ───────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager — modern replacement for @app.on_event("startup").

    STARTUP: Create all components once. They live on app.state for the
    entire lifetime of the application. No component is re-created per request.

    SHUTDOWN: Log final metrics summary. Clean up resources.
    """
    # ── Startup ──
    logger = setup_logger("docmind", level=10 if settings.debug else 20)
    logger.info("Starting DocMind API", extra={"version": settings.app_version})

    # Initialize all components
    app.state.agent = ProductionAgent()
    app.state.security = SecurityPipeline(
        max_input_length=settings.max_input_length,
        injection_threshold=settings.injection_threshold,
    )
    app.state.cache = ResponseCache(
        ttl=settings.cache_ttl,
        max_size=settings.cache_max_size,
    )
    app.state.metrics = MetricsCollector()
    app.state.start_time = time.time()

    # RAG components
    vector_store = VectorStore()
    app.state.vector_store = vector_store
    compression = CompressionService(enabled=True)
    retrieval = RetrievalService(vector_store=vector_store, compression_service=compression)
    app.state.retrieval = retrieval
    app.state.doc_service = DocumentService(vector_store=vector_store, retrieval_service=retrieval)
    app.state.memory = MemoryService(max_history=10)
    app.state.eval_service = EvaluationService(
        retrieval_service=retrieval,
        agent=app.state.agent,
    )

    logger.info(
        "All components initialized",
        extra={
            "primary_model": settings.primary_model,
            "fallback_model": settings.fallback_model,
            "rate_limit": settings.rate_limit,
            "cache_ttl": settings.cache_ttl,
        },
    )

    yield  # ← App is running, handling requests

    # ── Shutdown ──
    app.state.metrics.log_summary()
    logger.info("DocMind API shutting down")


# ─── App Creation ───────────────────────────────────────────────────────────


app = FastAPI(
    title="DocMind API",
    description="AI-powered Document Intelligence Platform with Production RAG",
    version=settings.app_version,
    lifespan=lifespan,
)


# ─── Rate Limiter ───────────────────────────────────────────────────────────
# Tracks requests per IP address. Returns 429 when limit exceeded.


limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ─── CORS Middleware ────────────────────────────────────────────────────────
# Allows the frontend (localhost:3000, etc.) to call our API.


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ─── Global Exception Handler ──────────────────────────────────────────────
# The user NEVER sees a raw stack trace. Always a clean JSON error.


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import logging
    import uuid

    logger = logging.getLogger("docmind")
    request_id = str(uuid.uuid4())[:8]

    logger.error(
        "Unhandled exception",
        extra={
            "request_id": request_id,
            "path": str(request.url.path),
            "error": str(exc),
            "type": type(exc).__name__,
        },
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "detail": "An unexpected error occurred. Please try again.",
            "request_id": request_id,
        },
    )


# ─── Mount Routers ──────────────────────────────────────────────────────────


app.include_router(chat_router, prefix="/api", tags=["Chat"])
app.include_router(stream_router, prefix="/api", tags=["Chat"])
app.include_router(documents_router, prefix="/api", tags=["Documents"])
app.include_router(evaluate_router, prefix="/api", tags=["Evaluation"])
app.include_router(health_router, prefix="/api", tags=["System"])


# ─── Root Endpoint ──────────────────────────────────────────────────────────


@app.get("/", tags=["Root"])
async def root():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/api/health",
    }
