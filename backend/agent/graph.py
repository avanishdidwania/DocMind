"""
LangGraph Production Agent — The Brain with a Safety Net.

This is NOT a raw LLM call wrapped in try/except.
Error handling is PART OF THE ARCHITECTURE — baked into the graph structure.

Flow:
    Query → [Primary Model] → Success? → Done
                             → Failure? → [Retry] → Success? → Done
                                                  → Failure? → [Fallback Model] → Success? → Done
                                                                                 → Failure? → [Error Response]
                                                                                              → Friendly message

The user NEVER sees a stack trace. Ever.
"""

import logging
import time
from typing import TypedDict, Optional, Annotated

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END

from config import settings

logger = logging.getLogger("docmind")


# ─── Helpers ────────────────────────────────────────────────────────────────


def _extract_text(content) -> str:
    """
    Extract plain text from LLM response content.
    Gemini can return either a string or a list of content blocks.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # Extract text from content blocks like [{'type': 'text', 'text': '...'}]
        parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


# ─── Agent State ────────────────────────────────────────────────────────────


class AgentState(TypedDict):
    """
    State that flows through the graph. Each node reads and updates this.

    This is the key LangGraph concept: explicit, typed state that accumulates
    information as it passes through nodes.
    """
    query: str                       # User's original question
    system_prompt: str               # System instructions for the LLM
    context: str                     # Retrieved document context (empty if no RAG)
    response: Optional[str]          # LLM's answer (None until generated)
    model_used: Optional[str]        # Which model produced the answer
    retries: int                     # How many times we've retried
    error: Optional[str]             # Last error message (for debugging)
    latency_ms: float                # Total processing time
    tokens_used: int                 # Token count for metrics


# ─── Message Builder ────────────────────────────────────────────────────────


def _build_messages(state: AgentState) -> list:
    """
    Build the message list for the LLM, with or without RAG context.

    Without context (general chat):
        [SystemMessage, HumanMessage(query)]

    With context (RAG):
        [SystemMessage, HumanMessage(context + query)]

    The context is injected into the user message so the LLM sees:
    "Here's relevant info from the document... Now answer this question..."
    """
    system_msg = SystemMessage(content=state["system_prompt"])

    context = state.get("context", "")

    if context:
        # RAG mode: inject context before the question
        user_content = (
            f"Use the following document context to answer the question. "
            f"Base your answer ONLY on this context. "
            f"If the answer isn't in the context, say so clearly.\n\n"
            f"--- DOCUMENT CONTEXT ---\n{context}\n--- END CONTEXT ---\n\n"
            f"Question: {state['query']}"
        )
    else:
        # General mode: just the question
        user_content = state["query"]

    human_msg = HumanMessage(content=user_content)

    return [system_msg, human_msg]


# ─── Node Functions ─────────────────────────────────────────────────────────
# Each node is a function: takes state → returns partial state update.
# LangGraph merges the returned dict into the existing state.


def call_primary_model(state: AgentState) -> dict:
    """
    Node: Call the primary (fast/cheap) model.
    This handles ~95% of requests successfully.
    """
    start = time.time()

    try:
        llm = ChatGoogleGenerativeAI(
            model=settings.primary_model,
            google_api_key=settings.google_api_key,
            temperature=settings.temperature,
        )

        messages = _build_messages(state)

        result = llm.invoke(messages)
        latency = (time.time() - start) * 1000

        logger.info(
            "Primary model success",
            extra={
                "model": settings.primary_model,
                "latency_ms": latency,
                "query_length": len(state["query"]),
            },
        )

        return {
            "response": _extract_text(result.content),
            "model_used": settings.primary_model,
            "latency_ms": state["latency_ms"] + latency,
            "tokens_used": result.usage_metadata.get("total_tokens", 0) if result.usage_metadata else 0,
            "error": None,
        }

    except Exception as e:
        latency = (time.time() - start) * 1000
        logger.warning(
            "Primary model failed",
            extra={
                "model": settings.primary_model,
                "error": str(e),
                "retries": state["retries"],
            },
        )

        return {
            "error": str(e),
            "retries": state["retries"] + 1,
            "latency_ms": state["latency_ms"] + latency,
        }


def call_fallback_model(state: AgentState) -> dict:
    """
    Node: Call the fallback (more capable/reliable) model.
    Only reached if primary model fails after retries.
    """
    start = time.time()

    try:
        llm = ChatGoogleGenerativeAI(
            model=settings.fallback_model,
            google_api_key=settings.google_api_key,
            temperature=settings.temperature,
        )

        messages = _build_messages(state)

        result = llm.invoke(messages)
        latency = (time.time() - start) * 1000

        logger.info(
            "Fallback model success",
            extra={
                "model": settings.fallback_model,
                "latency_ms": latency,
            },
        )

        return {
            "response": _extract_text(result.content),
            "model_used": settings.fallback_model,
            "latency_ms": state["latency_ms"] + latency,
            "tokens_used": result.usage_metadata.get("total_tokens", 0) if result.usage_metadata else 0,
            "error": None,
        }

    except Exception as e:
        latency = (time.time() - start) * 1000
        logger.error(
            "Fallback model also failed",
            extra={
                "model": settings.fallback_model,
                "error": str(e),
            },
        )

        return {
            "error": str(e),
            "latency_ms": state["latency_ms"] + latency,
        }


def generate_error_response(state: AgentState) -> dict:
    """
    Node: Generate a friendly error message.
    Both primary and fallback failed — but the user still gets a clean response.
    No stack trace. No 500 error. Just a helpful message.
    """
    logger.error(
        "All models failed — returning error response",
        extra={"last_error": state.get("error"), "retries": state["retries"]},
    )

    return {
        "response": (
            "I'm sorry, I'm temporarily unable to process your request. "
            "Please try again in a moment. If the issue persists, our team has been notified."
        ),
        "model_used": "error_fallback",
    }


# ─── Conditional Edge Functions (Routing Logic) ─────────────────────────────
# These decide WHERE to go next based on current state.


def after_primary(state: AgentState) -> str:
    """
    After primary model: where do we go?
    - Got a response? → Done
    - Failed but retries left? → Try primary again
    - Out of retries? → Fallback model
    """
    if state.get("response"):
        return "done"
    elif state["retries"] < settings.max_retries:
        return "retry"
    else:
        return "fallback"


def after_fallback(state: AgentState) -> str:
    """
    After fallback model: success or error response?
    """
    if state.get("response"):
        return "done"
    else:
        return "error"


# ─── Graph Construction ─────────────────────────────────────────────────────


def build_agent_graph() -> StateGraph:
    """
    Build the LangGraph agent with the safety net pattern.

    Graph structure:
        primary → (conditional) → done | retry(primary) | fallback
        fallback → (conditional) → done | error
        error → done
    """
    graph = StateGraph(AgentState)

    # Add nodes (each is a function that processes state)
    graph.add_node("primary", call_primary_model)
    graph.add_node("fallback", call_fallback_model)
    graph.add_node("error", generate_error_response)

    # Entry point — always start with primary model
    graph.set_entry_point("primary")

    # Conditional edges from primary node
    graph.add_conditional_edges(
        "primary",
        after_primary,
        {
            "done": END,           # Success → finish
            "retry": "primary",    # Failed → loop back (retry)
            "fallback": "fallback",  # Retries exhausted → try fallback
        },
    )

    # Conditional edges from fallback node
    graph.add_conditional_edges(
        "fallback",
        after_fallback,
        {
            "done": END,    # Fallback succeeded → finish
            "error": "error",  # Fallback also failed → error message
        },
    )

    # Error node always ends
    graph.add_edge("error", END)

    return graph


# ─── Production Agent Class ─────────────────────────────────────────────────


DEFAULT_SYSTEM_PROMPT = """You are DocMind, an intelligent document analysis assistant.

Your capabilities:
- Answer questions based on provided document context
- Analyze data, tables, and structured content
- Provide clear, well-structured responses with citations

Guidelines:
- Base answers on provided context when available
- Be concise but thorough
- If you don't know something, say so clearly
- Always cite which part of the document you're referencing"""


class ProductionAgent:
    """
    Production-ready LangGraph agent.

    Wraps the graph into a clean interface that main.py can use.
    Initialized once at startup, shared across all requests via app.state.
    """

    def __init__(self):
        """Build and compile the graph. Called once at startup."""
        graph = build_agent_graph()
        self.runnable = graph.compile()
        logger.info(
            "ProductionAgent initialized",
            extra={
                "primary_model": settings.primary_model,
                "fallback_model": settings.fallback_model,
                "max_retries": settings.max_retries,
            },
        )

    async def invoke(
        self,
        query: str,
        context: str = "",
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> AgentState:
        """
        Process a user query through the agent graph.

        Args:
            query: The user's message (already sanitized + PII-masked by security pipeline)
            context: Retrieved document context (empty string = no RAG, just chat)
            system_prompt: System instructions (can be customized per chat mode)

        Returns:
            AgentState with response, model_used, latency_ms, tokens_used
        """
        initial_state: AgentState = {
            "query": query,
            "system_prompt": system_prompt,
            "context": context,
            "response": None,
            "model_used": None,
            "retries": 0,
            "error": None,
            "latency_ms": 0.0,
            "tokens_used": 0,
        }

        # ainvoke for async execution
        result = await self.runnable.ainvoke(initial_state)

        logger.info(
            "Agent invocation complete",
            extra={
                "model_used": result.get("model_used"),
                "latency_ms": result.get("latency_ms"),
                "retries": result.get("retries"),
                "had_error": result.get("model_used") == "error_fallback",
            },
        )

        return result
