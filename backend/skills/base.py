"""
Skills Framework — Base class and result types.

A skill is a specialized capability that the agent can invoke.
Each skill does ONE thing well:
- Document Q&A: answer questions from uploaded PDFs
- Fact Checker: verify claims using nolie-agent
- General Chat: direct LLM response

The Intent Router decides which skill to use based on the user's query.
"""

from dataclasses import dataclass, field
from abc import ABC, abstractmethod


@dataclass
class SkillResult:
    """Result returned by any skill."""
    response: str                          # The main answer text
    skill_used: str                        # Which skill produced this ("document_qa", "fact_checker", "general")
    sources: list[str] = field(default_factory=list)    # Citations / evidence sources
    metadata: dict = field(default_factory=dict)        # Skill-specific extra data
    confidence: str = ""                   # Optional confidence level


class BaseSkill(ABC):
    """Abstract base class for all skills."""

    name: str = "base"
    description: str = "Base skill"

    @abstractmethod
    async def execute(self, query: str, context: dict) -> SkillResult:
        """
        Execute the skill.

        Args:
            query: The user's message (already cleaned by security pipeline)
            context: Additional context dict with keys like:
                - document_id: str | None
                - document_ids: list[str] | None
                - session_id: str | None
                - history: str (conversation history)
                - mode: str ("general" | "analytical")

        Returns:
            SkillResult with response, skill name, sources, metadata
        """
        ...
