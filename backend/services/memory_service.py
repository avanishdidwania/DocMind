"""
Conversation Memory — Stateful chat with history.

Without memory: every message is independent. The LLM forgets what you just said.
With memory: the LLM sees the last N messages, can follow up, reference earlier questions.

This is what makes it feel like a PRODUCT, not a demo.

Storage: In-memory dict (dev). Production: Redis or PostgreSQL.
The interface stays the same — swap the backend, no code changes.
"""

import time
import uuid
import logging
from dataclasses import dataclass, field

logger = logging.getLogger("docmind")


# ─── Data Models ────────────────────────────────────────────────────────────


@dataclass
class ChatMessage:
    """A single message in a conversation."""
    role: str           # "user" or "assistant"
    content: str        # The message text
    timestamp: float = field(default_factory=time.time)


@dataclass
class ChatSession:
    """A conversation session with its message history."""
    session_id: str
    document_id: str | None = None   # Which document this chat is about
    messages: list[ChatMessage] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def message_count(self) -> int:
        return len(self.messages)


# ─── Memory Service ─────────────────────────────────────────────────────────


class MemoryService:
    """
    Manages chat sessions and conversation history.

    Key design decisions:
    - Max history window (don't send 1000 messages to the LLM — too many tokens)
    - Per-session isolation (different documents = different conversations)
    - Formatted for LLM injection (role: content pairs)
    """

    def __init__(self, max_history: int = 10):
        """
        Args:
            max_history: Maximum messages to include in LLM context.
                         10 = last 5 user messages + 5 assistant responses.
                         More history = more context but more tokens ($$$).
        """
        self.max_history = max_history
        self._sessions: dict[str, ChatSession] = {}

        logger.info("MemoryService initialized", extra={"max_history": max_history})

    def get_or_create_session(
        self,
        session_id: str | None = None,
        document_id: str | None = None,
    ) -> ChatSession:
        """
        Get an existing session or create a new one.

        Args:
            session_id: Existing session to continue (None = create new)
            document_id: Document this chat is about

        Returns:
            The ChatSession (existing or newly created)
        """
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]

        # Create new session
        new_id = session_id or str(uuid.uuid4())[:12]
        session = ChatSession(session_id=new_id, document_id=document_id)
        self._sessions[new_id] = session

        logger.info(
            "New chat session created",
            extra={"session_id": new_id, "document_id": document_id},
        )

        return session

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """
        Add a message to a session's history.

        Args:
            session_id: Which session
            role: "user" or "assistant"
            content: The message text
        """
        session = self._sessions.get(session_id)
        if not session:
            return

        session.messages.append(ChatMessage(role=role, content=content))
        session.updated_at = time.time()

    def get_history_for_prompt(self, session_id: str) -> str:
        """
        Get formatted conversation history for LLM injection.

        Returns the last N messages formatted as:
            User: ...
            Assistant: ...
            User: ...
            Assistant: ...

        This gets prepended to the current query so the LLM
        has conversational context.
        """
        session = self._sessions.get(session_id)
        if not session or not session.messages:
            return ""

        # Get last N messages (excluding the current one being processed)
        recent = session.messages[-self.max_history:]

        # Format for the LLM
        formatted_parts = []
        for msg in recent:
            role_label = "User" if msg.role == "user" else "Assistant"
            formatted_parts.append(f"{role_label}: {msg.content}")

        return "\n".join(formatted_parts)

    def get_session(self, session_id: str) -> ChatSession | None:
        """Get a specific session."""
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[dict]:
        """List all sessions with basic metadata."""
        return [
            {
                "session_id": session.session_id,
                "document_id": session.document_id,
                "message_count": session.message_count,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
            }
            for session in sorted(
                self._sessions.values(),
                key=lambda s: s.updated_at,
                reverse=True,
            )
        ]

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its history."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False
