"""
Document Q&A Skill — RAG over uploaded documents.

This wraps the existing retrieval + agent pipeline as a skill.
Already built — just packaged into the skill interface.
"""

import logging

from skills.base import BaseSkill, SkillResult
from services.retrieval_service import RetrievalService
from agent.graph import ProductionAgent, DEFAULT_SYSTEM_PROMPT, ANALYTICAL_SYSTEM_PROMPT

logger = logging.getLogger("docmind")


class DocumentQASkill(BaseSkill):
    """Answer questions from uploaded documents using RAG."""

    name = "document_qa"
    description = (
        "Answer questions based on uploaded PDF documents. "
        "Uses hybrid retrieval, self-correcting RAG, and grounded generation."
    )

    def __init__(self, retrieval_service: RetrievalService, agent: ProductionAgent):
        self.retrieval = retrieval_service
        self.agent = agent

    async def execute(self, query: str, context: dict) -> SkillResult:
        """Retrieve context from documents and generate grounded answer."""
        document_id = context.get("document_id")
        document_ids = context.get("document_ids", [])
        mode = context.get("mode", "general")
        history = context.get("history", "")

        # Retrieve context
        rag_context = ""
        sources = []

        if document_ids and len(document_ids) > 1:
            retrieval_result = await self.retrieval.retrieve_multi(
                query=query, document_ids=document_ids
            )
        elif document_id:
            retrieval_result = await self.retrieval.retrieve_with_correction(
                query=query, document_id=document_id
            )
        else:
            return SkillResult(
                response="No documents selected. Please upload and select a document to query.",
                skill_used=self.name,
            )

        if retrieval_result.has_context:
            rag_context = retrieval_result.context
            sources = retrieval_result.sources

        # Build query with history
        query_with_history = query
        if history:
            query_with_history = f"Conversation so far:\n{history}\n\nCurrent question: {query}"

        # Select system prompt
        system_prompt = ANALYTICAL_SYSTEM_PROMPT if mode == "analytical" else DEFAULT_SYSTEM_PROMPT

        # Generate answer
        agent_result = await self.agent.invoke(
            query=query_with_history,
            context=rag_context,
            system_prompt=system_prompt,
        )

        return SkillResult(
            response=agent_result.get("response", "No response generated."),
            skill_used=self.name,
            sources=sources,
            metadata={
                "model_used": agent_result.get("model_used"),
                "tokens_used": agent_result.get("tokens_used", 0),
                "chunks_retrieved": len(sources),
            },
        )
