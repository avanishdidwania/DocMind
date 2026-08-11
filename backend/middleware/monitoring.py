"""
Monitoring — Structured JSON Logger + MetricsCollector.

Two components:

1. JSONLogger: Replaces print() with structured, machine-parseable log output.
   Log aggregators (ELK, Datadog, CloudWatch) need JSON to search, filter, alert.

2. MetricsCollector: Tracks request counts, latency, errors, cache hits, tokens.
   In-memory counters for dev. Production swap: Prometheus.

Rule: We NEVER use print() in production.
"""

import json
import time
import logging
import sys
from datetime import datetime, timezone
from threading import Lock


# ─── Structured JSON Logger ─────────────────────────────────────────────────


class JSONFormatter(logging.Formatter):
    """
    Custom log formatter that outputs structured JSON.

    Every log entry is a single JSON line with consistent fields.
    Log aggregators parse this automatically — no custom parsing rules needed.

    Example output:
    {"timestamp": "2026-08-11T14:30:00Z", "level": "ERROR", "message": "LLM call failed",
     "model": "gemini-2.0-flash", "latency_ms": 5200, "error_type": "timeout"}
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add any extra fields passed via logger.info("msg", extra={...})
        # This is how we attach request_id, user_id, latency, etc.
        if hasattr(record, "__dict__"):
            for key, value in record.__dict__.items():
                if key not in (
                    "name", "msg", "args", "created", "filename", "funcName",
                    "levelname", "levelno", "lineno", "module", "msecs",
                    "pathname", "process", "processName", "relativeCreated",
                    "stack_info", "thread", "threadName", "exc_info", "exc_text",
                    "message", "taskName",
                ):
                    log_entry[key] = value

        # Add exception info if present
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def setup_logger(name: str = "docmind", level: int = logging.INFO) -> logging.Logger:
    """
    Configure and return a structured JSON logger.

    Call this ONCE at startup. All modules then use:
        logger = logging.getLogger("docmind")
        logger.info("Something happened", extra={"request_id": "abc", "latency_ms": 150})
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers if called multiple times
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)

    # Prevent propagation to root logger (avoids duplicate output)
    logger.propagate = False

    return logger


# ─── Metrics Collector ──────────────────────────────────────────────────────


class MetricsCollector:
    """
    Tracks application metrics for the /metrics endpoint.

    Current: In-memory counters (dict-based).
    Production: Prometheus Counter/Histogram/Gauge objects.

    What we track and WHY:
    - request_count: traffic volume, billing
    - error_count + error_rate: system health
    - latency: user experience (track avg, we'd want percentiles in prod)
    - cache_hits/misses: cost efficiency
    - token_usage: LLM cost tracking
    - model_usage: how often fallback fires (reliability signal)
    - injection_attempts: security monitoring
    - rate_limit_hits: abuse detection
    """

    def __init__(self):
        self._lock = Lock()
        self._start_time = time.time()

        # Core metrics
        self.request_count = 0
        self.error_count = 0
        self.total_latency_ms = 0.0

        # Cache metrics
        self.cache_hits = 0
        self.cache_misses = 0

        # LLM metrics
        self.total_tokens = 0
        self.model_usage: dict[str, int] = {}  # model_name → request count

        # Security metrics
        self.injection_attempts = 0
        self.pii_detections = 0
        self.rate_limit_hits = 0

    def record_request(
        self,
        latency_ms: float,
        model_used: str,
        tokens_used: int = 0,
        cached: bool = False,
        error: bool = False,
    ) -> None:
        """Record metrics for a completed request."""
        with self._lock:
            self.request_count += 1
            self.total_latency_ms += latency_ms

            if cached:
                self.cache_hits += 1
            else:
                self.cache_misses += 1

            if error:
                self.error_count += 1

            self.total_tokens += tokens_used
            self.model_usage[model_used] = self.model_usage.get(model_used, 0) + 1

    def record_security_event(
        self, injection: bool = False, pii: bool = False, rate_limited: bool = False
    ) -> None:
        """Record a security-related event."""
        with self._lock:
            if injection:
                self.injection_attempts += 1
            if pii:
                self.pii_detections += 1
            if rate_limited:
                self.rate_limit_hits += 1

    @property
    def uptime_seconds(self) -> float:
        """How long the service has been running."""
        return time.time() - self._start_time

    def summary(self) -> dict:
        """
        Full metrics summary for the /metrics endpoint.
        """
        with self._lock:
            total_cache_requests = self.cache_hits + self.cache_misses
            return {
                "total_requests": self.request_count,
                "error_rate": (
                    self.error_count / self.request_count
                    if self.request_count > 0
                    else 0.0
                ),
                "avg_latency_ms": (
                    self.total_latency_ms / self.request_count
                    if self.request_count > 0
                    else 0.0
                ),
                "cache_hit_rate": (
                    self.cache_hits / total_cache_requests
                    if total_cache_requests > 0
                    else 0.0
                ),
                "total_tokens_used": self.total_tokens,
                "model_usage": dict(self.model_usage),
                "uptime_seconds": self.uptime_seconds,
                "security": {
                    "injection_attempts": self.injection_attempts,
                    "pii_detections": self.pii_detections,
                    "rate_limit_hits": self.rate_limit_hits,
                },
            }

    def log_summary(self) -> None:
        """Log the final metrics summary (called on shutdown)."""
        logger = logging.getLogger("docmind")
        summary = self.summary()
        logger.info(
            "Metrics summary at shutdown",
            extra={"metrics": summary},
        )
