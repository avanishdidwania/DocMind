"""
General Chat Skill — Direct LLM response without retrieval.

For general questions that don't need documents or fact-checking.
"""

import logging

from skills.base import BaseSkill, SkillResult
from agent.graph import ProductionAgent, DEFAULT_SYSTEM_PROMPT

logger = logging.getLogger("docmind")


class GeneralChatSkill(BaseSkill):
    """Direct LLM chat without RAG or fact-checking."""

    name = "general"
    description = (
        "General conversation, math, coding help, explanations. "
        "No document retrieval or fact-checking needed."
    )

    def __init__(self, agent: ProductionAgent):
        self.agent = agent

    async def execute(self, query: str, context: dict) -> SkillResult:
        """Send query directly to LLM."""
        history = context.get("history", "")

        query_with_history = query
        if history:
            query_with_history = f"Conversation so far:\n{history}\n\nCurrent question: {query}"

        agent_result = await self.agent.invoke(
            query=query_with_history,
            context="",
            system_prompt=DEFAULT_SYSTEM_PROMPT,
        )

        return SkillResult(
            response=agent_result.get("response", "No response generated."),
            skill_used=self.name,
            metadata={
                "model_used": agent_result.get("model_used"),
                "tokens_used": agent_result.get("tokens_used", 0),
            },
        )
