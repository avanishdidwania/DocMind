"""
Chat Endpoint — The main one. Full production pipeline in one endpoint.

Flow (in order):
1. Rate limit check (slowapi decorator)
2. Security pipeline → reject if blocked
3. Get/create session + load conversation history
4. Cache lookup → return instantly if hit
5. Retrieve document context (RAG) if document_id provided
6. LangGraph agent invoke → get LLM response
7. Save to memory + cache store
8. Record metrics → track everything
9. Return JSON response

This is where ALL the middleware layers come together.
"""

import time
import uuid
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from models.schemas import ChatRequest, ChatResponse, StandardErrorResponse, SecurityVerdict
from config import settings

router = APIRouter()
logger = logging.getLogger("docmind")

# Rate limiter instance (shared with main app)
limiter = Limiter(key_func=get_remote_address)


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        400: {"model": StandardErrorResponse, "description": "Blocked by security"},
        429: {"description": "Rate limit exceeded"},
        500: {"model": StandardErrorResponse, "description": "Internal error"},
    },
)
@limiter.limit(settings.rate_limit)
async def chat(request: Request, body: ChatRequest):
    """
    Send a message to the AI assistant.

    The request passes through the full production pipeline:
    rate limit → security → memory → cache → retrieval → agent → memory → cache → metrics → response
    """
    start_time = time.time()
    request_id = str(uuid.uuid4())[:8]

    # Get components from app.state (created once at startup)
    security = request.app.state.security
    cache = request.app.state.cache
    agent = request.app.state.agent
    metrics = request.app.state.metrics
    memory = request.app.state.memory

    # ─── Step 1: Security Pipeline ──────────────────────────────────────
    security_result = security.process(body.message)

    if security_result.verdict == SecurityVerdict.blocked:
        metrics.record_security_event(injection=True)
        logger.warning(
            "Request blocked by security",
            extra={
                "request_id": request_id,
                "reason": security_result.reason,
                "score": security_result.injection_score,
            },
        )
        return JSONResponse(
            status_code=400,
            content={
                "error": "security_blocked",
                "detail": security_result.reason,
                "request_id": request_id,
            },
        )

    if security_result.pii_detected:
        metrics.record_security_event(pii=True)

    cleaned_query = security_result.cleaned_input

    # ─── Step 2: Session + Memory ───────────────────────────────────────
    # Get or create a conversation session
    session = memory.get_or_create_session(
        session_id=body.session_id,
        document_id=body.document_id,
    )
    session_id = session.session_id

    # Get conversation history (last N messages for context)
    history = memory.get_history_for_prompt(session_id)

    # Save the user's message to memory
    memory.add_message(session_id, role="user", content=cleaned_query)

    # ─── Step 3: Cache Lookup ───────────────────────────────────────────
    # Only use cache for stateless queries (no session history)
    # If there's conversation context, skip cache (answers depend on history)
    if not history:
        cached_entry = cache.get(cleaned_query)
        if cached_entry:
            latency_ms = (time.time() - start_time) * 1000
            metrics.record_request(
                latency_ms=latency_ms,
                model_used="cache",
                tokens_used=0,
                cached=True,
            )
            # Save cached response to memory too
            memory.add_message(session_id, role="assistant", content=cached_entry.response)

            return ChatResponse(
                response=cached_entry.response,
                session_id=session_id,
                model_used=cached_entry.model_used,
                cached=True,
                latency_ms=latency_ms,
            )

    # ─── Step 4: Skill Router ──────────────────────────────────────────
    # The router classifies intent and dispatches to the right skill:
    # - "document_qa" → RAG over uploaded docs (hybrid + self-correcting)
    # - "fact_check" → calls nolie-agent for claim verification
    # - "general" → direct LLM response
    # - "combined" → both document QA + fact-check

    skill_router = request.app.state.skill_router

    skill_context = {
        "document_id": body.document_id,
        "document_ids": body.document_ids,
        "session_id": session_id,
        "history": history,
        "mode": body.mode,
    }

    skill_result = await skill_router.route(query=cleaned_query, context=skill_context)

    response_text = skill_result.response or "No response generated."
    sources = skill_result.sources
    model_used = skill_result.metadata.get("model_used", skill_result.skill_used)
    tokens_used = skill_result.metadata.get("tokens_used", 0)

    # ─── Step 5: Save to Memory + Cache ────────────────────────────────
    # Save assistant response to conversation memory
    memory.add_message(session_id, role="assistant", content=response_text)

    # Cache the response (only if no conversation history — stateless queries)
    if not history and skill_result.skill_used != "fact_checker":
        cache.set(cleaned_query, response_text, model_used)

    # ─── Step 6: Record Metrics ────────────────────────────────────────
    latency_ms = (time.time() - start_time) * 1000

    metrics.record_request(
        latency_ms=latency_ms,
        model_used=model_used,
        tokens_used=tokens_used,
        cached=False,
        error=False,
    )

    logger.info(
        "Request completed",
        extra={
            "request_id": request_id,
            "session_id": session_id,
            "model_used": model_used,
            "latency_ms": latency_ms,
            "tokens_used": tokens_used,
            "cached": False,
            "has_history": bool(history),
        },
    )

    # ─── Step 7: Return Response ───────────────────────────────────────
    return ChatResponse(
        response=response_text,
        session_id=session_id,
        model_used=model_used,
        cached=False,
        latency_ms=latency_ms,
        sources=sources,
        metadata={
            "request_id": request_id,
            "skill_used": skill_result.skill_used,
            "tokens_used": tokens_used,
            "security_verdict": security_result.verdict.value,
            "pii_masked": security_result.pii_detected,
            "document_id": body.document_id,
            "chunks_retrieved": len(sources),
            "conversation_turns": session.message_count,
            **skill_result.metadata,
        },
    )


@router.get("/chat/sessions")
async def list_sessions(request: Request):
    """List all active chat sessions."""
    memory = request.app.state.memory
    return {"sessions": memory.list_sessions()}


@router.delete("/chat/sessions/{session_id}")
async def delete_session(request: Request, session_id: str):
    """Delete a chat session and its history."""
    memory = request.app.state.memory
    deleted = memory.delete_session(session_id)
    if not deleted:
        return JSONResponse(status_code=404, content={"error": "Session not found"})
    return {"deleted": True, "session_id": session_id}
