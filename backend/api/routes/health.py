"""
System Endpoints — Health, Metrics, Cache Stats.

These are NOT user-facing. They're for:
- Load balancers (health check → route traffic only to healthy instances)
- Docker HEALTHCHECK (restart container if unhealthy)
- Monitoring dashboards (Grafana pulls from /metrics)
- Debugging (is the cache working? what's the error rate?)
"""

import time
import logging

from fastapi import APIRouter, Request

from models.schemas import HealthResponse, MetricsResponse, CacheStatsResponse
from config import settings

router = APIRouter()
logger = logging.getLogger("docmind")


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request):
    """
    Health check endpoint.

    Used by:
    - Docker HEALTHCHECK (restart if this fails)
    - Load balancers (stop routing traffic to unhealthy instances)
    - Uptime monitors (alert if down)

    Returns component-level status so you know WHAT broke.
    """
    components = {}

    # Check agent
    try:
        agent = request.app.state.agent
        components["agent"] = "healthy" if agent else "not_initialized"
    except Exception:
        components["agent"] = "unhealthy"

    # Check cache
    try:
        cache = request.app.state.cache
        components["cache"] = "healthy" if cache else "not_initialized"
    except Exception:
        components["cache"] = "unhealthy"

    # Check security
    try:
        security = request.app.state.security
        components["security"] = "healthy" if security else "not_initialized"
    except Exception:
        components["security"] = "unhealthy"

    # Check vector store
    try:
        vs = request.app.state.vector_store
        components["vector_store"] = f"healthy ({vs.backend})"
    except Exception:
        components["vector_store"] = "unhealthy"

    # Overall status
    all_healthy = all("healthy" in v for v in components.values())
    uptime = time.time() - request.app.state.start_time

    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        version=settings.app_version,
        uptime_seconds=uptime,
        components=components,
    )


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(request: Request):
    """
    Current system metrics.

    In production this would be a Prometheus /metrics endpoint
    in the OpenMetrics format. For now, JSON summary.
    """
    metrics = request.app.state.metrics
    summary = metrics.summary()

    return MetricsResponse(
        total_requests=summary["total_requests"],
        error_rate=summary["error_rate"],
        avg_latency_ms=summary["avg_latency_ms"],
        cache_hit_rate=summary["cache_hit_rate"],
        total_tokens_used=summary["total_tokens_used"],
        model_usage=summary["model_usage"],
        uptime_seconds=summary["uptime_seconds"],
    )


@router.get("/cache/stats", response_model=CacheStatsResponse)
async def cache_stats(request: Request):
    """
    Cache statistics.

    Useful for:
    - Is the cache actually helping? (check hit_rate)
    - Is it too full? (entries vs max_size)
    - Should we adjust TTL? (if hit_rate is low, TTL might be too short)
    """
    cache = request.app.state.cache
    stats = cache.stats()

    return CacheStatsResponse(
        entries=stats["entries"],
        hit_count=stats["hit_count"],
        miss_count=stats["miss_count"],
        hit_rate=stats["hit_rate"],
        size_bytes=stats["size_bytes"],
        ttl_seconds=stats["ttl_seconds"],
    )


@router.post("/cache/clear")
async def clear_cache(request: Request):
    """
    Clear all cached responses.

    Use when: knowledge base changes (documents re-indexed),
    model updated, or cached answers are stale.
    """
    cache = request.app.state.cache
    cleared = cache.clear()

    logger.info("Cache cleared via API", extra={"entries_cleared": cleared})

    return {"cleared": cleared, "message": f"Cleared {cleared} cached entries"}
