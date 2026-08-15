"""
Streaming Chat Endpoint — Server-Sent Events (SSE).

Instead of waiting 3-5 seconds for a full response, the user sees
tokens appear as they're generated. This is table-stakes for modern AI products.

How it works:
1. Same pipeline as /api/chat (security → retrieval → context)
2. Instead of agent.invoke(), we stream directly from the LLM
3. FastAPI StreamingResponse sends each token chunk as an SSE event
4. Client reads the event stream and renders text progressively

Protocol: Server-Sent Events (SSE)
- Content-Type: text/event-stream
- Each chunk: data: {"token": "...", "done": false}\n\n
- Final chunk: data: {"token": "", "done": true, "metadata": {...}}\n\n
"""

import time
import uuid
import json
import logging
import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from models.schemas import ChatRequest, SecurityVerdict
from config import settings
from agent.graph import DEFAULT_SYSTEM_PROMPT, ANALYTICAL_SYSTEM_PROMPT, _extract_text, _create_llm

router = APIRouter()
logger = logging.getLogger("docmind")
limiter = Limiter(key_func=get_remote_address)


@router.post("/chat/stream")
@limiter.limit(settings.rate_limit)
async def chat_stream(request: Request, body: ChatRequest):
    """
    Stream a response token-by-token via Server-Sent Events.

    Same security + retrieval pipeline as /api/chat, but the LLM response
    is streamed instead of returned all at once.

    Client usage (JavaScript):
        const evtSource = new EventSource('/api/chat/stream', { method: 'POST', body: ... });
        // Or using fetch:
        const response = await fetch('/api/chat/stream', { method: 'POST', body: JSON.stringify({message: '...'}) });
        const reader = response.body.getReader();
    """
    start_time = time.time()
    request_id = str(uuid.uuid4())[:8]

    # Get components
    security = request.app.state.security
    metrics = request.app.state.metrics
    memory = request.app.state.memory

    # ─── Security Check ─────────────────────────────────────────────────
    security_result = security.process(body.message)

    if security_result.verdict == SecurityVerdict.blocked:
        metrics.record_security_event(injection=True)
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

    # ─── Session + Memory ───────────────────────────────────────────────
    session = memory.get_or_create_session(
        session_id=body.session_id,
        document_id=body.document_id,
    )
    session_id = session.session_id
    history = memory.get_history_for_prompt(session_id)
    memory.add_message(session_id, role="user", content=cleaned_query)

    # ─── Retrieval ──────────────────────────────────────────────────────
    context = ""
    sources = []
    retrieval = getattr(request.app.state, "retrieval", None)

    if body.document_id and retrieval:
        retrieval_result = await retrieval.retrieve_with_correction(
            query=cleaned_query,
            document_id=body.document_id,
        )
        if retrieval_result.has_context:
            context = retrieval_result.context
            sources = retrieval_result.sources

    # ─── Build Messages ─────────────────────────────────────────────────
    system_prompt = ANALYTICAL_SYSTEM_PROMPT if body.mode == "analytical" else DEFAULT_SYSTEM_PROMPT

    query_with_history = cleaned_query
    if history:
        query_with_history = f"Conversation so far:\n{history}\n\nCurrent question: {cleaned_query}"

    if context:
        user_content = (
            f"Use the following document context to answer the question. "
            f"Base your answer ONLY on this context. "
            f"If the answer isn't in the context, say so clearly.\n\n"
            f"--- DOCUMENT CONTEXT ---\n{context}\n--- END CONTEXT ---\n\n"
            f"Question: {query_with_history}"
        )
    else:
        user_content = query_with_history

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_content),
    ]

    # ─── Stream Generator ───────────────────────────────────────────────

    async def generate_stream():
        """Async generator that yields SSE events with tokens."""
        full_response = ""

        try:
            llm = _create_llm(settings.primary_model)

            async for chunk in llm.astream(messages):
                token = _extract_text(chunk.content)
                if token:
                    full_response += token
                    # SSE format: data: <json>\n\n
                    event = json.dumps({"token": token, "done": False})
                    yield f"data: {event}\n\n"

        except Exception as e:
            logger.error("Streaming failed", extra={"error": str(e), "request_id": request_id})
            error_msg = "I'm sorry, I'm temporarily unable to process your request."
            full_response = error_msg
            event = json.dumps({"token": error_msg, "done": False})
            yield f"data: {event}\n\n"

        # Final event with metadata
        latency_ms = (time.time() - start_time) * 1000

        # Save to memory
        memory.add_message(session_id, role="assistant", content=full_response)

        # Record metrics
        metrics.record_request(
            latency_ms=latency_ms,
            model_used=settings.primary_model,
            tokens_used=0,  # Hard to get exact count in streaming mode
            cached=False,
        )

        # Send done event
        done_event = json.dumps({
            "token": "",
            "done": True,
            "metadata": {
                "session_id": session_id,
                "model_used": settings.primary_model,
                "latency_ms": latency_ms,
                "sources": sources,
                "request_id": request_id,
            },
        })
        yield f"data: {done_event}\n\n"

        logger.info(
            "Stream completed",
            extra={
                "request_id": request_id,
                "session_id": session_id,
                "latency_ms": latency_ms,
                "response_length": len(full_response),
            },
        )

    # ─── Return Streaming Response ──────────────────────────────────────
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Request-ID": request_id,
        },
    )
