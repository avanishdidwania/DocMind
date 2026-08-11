"""
Pydantic models for API request/response validation.

These serve three purposes:
1. Auto-validate incoming requests (wrong type → 422 automatically)
2. Auto-serialize outgoing responses (Python objects → JSON)
3. Auto-generate OpenAPI docs (Swagger UI at /docs)

The frontend team always knows exactly what shape the data will be.
"""

from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


# ─── Enums ──────────────────────────────────────────────────────────────────


class ChatMode(str, Enum):
    """Types of chat interaction."""
    general = "general"          # Open Q&A with document context
    analytical = "analytical"    # Table/data focused analysis


class SecurityVerdict(str, Enum):
    """Result of security pipeline check."""
    safe = "safe"
    suspicious = "suspicious"
    blocked = "blocked"


# ─── Request Models ─────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    """Incoming chat message from the user."""
    message: str = Field(..., min_length=1, max_length=10000, description="User's message")
    session_id: str | None = Field(None, description="Existing session to continue")
    document_id: str | None = Field(None, description="Single document to chat about")
    document_ids: list[str] | None = Field(None, description="Multiple documents to chat across")
    mode: ChatMode = Field(ChatMode.general, description="Chat mode")


class DocumentUploadResponse(BaseModel):
    """Response after a document is uploaded and processed."""
    document_id: str
    filename: str
    page_count: int
    chunks_created: int
    processing_time_ms: float


# ─── Response Models ────────────────────────────────────────────────────────


class ChatResponse(BaseModel):
    """Response from the chat endpoint."""
    response: str = Field(..., description="AI-generated answer")
    session_id: str = Field(..., description="Session ID for continuity")
    model_used: str = Field(..., description="Which model generated this response")
    cached: bool = Field(False, description="Whether response came from cache")
    latency_ms: float = Field(..., description="Total processing time in milliseconds")
    sources: list[str] = Field(default_factory=list, description="Document chunks used")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")


class HealthResponse(BaseModel):
    """Health check response — used by load balancers and Docker HEALTHCHECK."""
    status: str = Field(..., description="'healthy' or 'unhealthy'")
    version: str
    uptime_seconds: float
    components: dict = Field(
        default_factory=dict,
        description="Status of sub-components (agent, cache, db)"
    )


class MetricsResponse(BaseModel):
    """Current system metrics — for monitoring dashboards."""
    total_requests: int
    error_rate: float = Field(..., description="Errors / total requests (0.0 - 1.0)")
    avg_latency_ms: float
    cache_hit_rate: float = Field(..., description="Cache hits / (hits + misses)")
    total_tokens_used: int
    model_usage: dict[str, int] = Field(
        default_factory=dict,
        description="Request count per model"
    )
    uptime_seconds: float


class CacheStatsResponse(BaseModel):
    """Cache statistics."""
    entries: int
    hit_count: int
    miss_count: int
    hit_rate: float
    size_bytes: int
    ttl_seconds: int


class StandardErrorResponse(BaseModel):
    """
    Consistent error format.
    The client ALWAYS gets this shape on errors — never a raw stack trace.
    """
    error: str = Field(..., description="Error type/code")
    detail: str = Field(..., description="Human-readable explanation")
    request_id: str = Field(..., description="For support/debugging reference")
    timestamp: datetime = Field(default_factory=datetime.now)


# ─── Security Models ────────────────────────────────────────────────────────


class SecurityResult(BaseModel):
    """Result from the security pipeline."""
    verdict: SecurityVerdict
    cleaned_input: str = Field("", description="Sanitized + PII-masked input")
    pii_detected: list[str] = Field(default_factory=list, description="Types of PII found")
    injection_score: float = Field(0.0, description="0.0 = safe, 1.0 = definite injection")
    reason: str = Field("", description="Why it was blocked (if blocked)")
