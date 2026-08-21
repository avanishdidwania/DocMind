"""
Intent Router — Classifies user queries and dispatches to the right skill.

This is the "brain" that decides:
- "Is it true that..." → Fact Checker
- "What does the document say about..." → Document Q&A
- "What is 2+2?" → General Chat
- "Does my document support this claim?" → Combined (both)

Uses a fast LLM call to classify intent. Takes ~200ms.
"""

import logging
from langchain_core.messages import HumanMessage

from skills.base import BaseSkill, SkillResult
from skills.fact_checker import FactCheckerSkill
from skills.document_qa import DocumentQASkill
from skills.general_chat import GeneralChatSkill
from agent.graph import _create_llm, _extract_text
from config import settings

logger = logging.getLogger("docmind")


ROUTER_PROMPT = """Classify this user query into EXACTLY ONE category. Respond with ONLY the category name, nothing else.

Categories:
- "fact_check": User wants to verify if something is true/false, check a claim, assess credibility, or asks "is it true that..."
- "document_qa": User asks about uploaded documents, wants information from their files, references "the document" or "this PDF"
- "combined": User wants to cross-reference their documents with fact-checking (e.g., "does my document support this claim?")
- "general": General questions, math, coding, explanations, conversation — no documents or fact-checking needed

Additional context:
- Has documents uploaded: {has_documents}
- Has documents selected: {has_selection}

User query: "{query}"

Category:"""


class SkillRouter:
    """
    Routes user queries to the appropriate skill.

    Flow:
    1. LLM classifies the intent (~200ms)
    2. Dispatch to the matching skill
    3. Return SkillResult
    """

    def __init__(
        self,
        fact_checker: FactCheckerSkill,
        document_qa: DocumentQASkill,
        general_chat: GeneralChatSkill,
    ):
        self.skills = {
            "fact_check": fact_checker,
            "document_qa": document_qa,
            "general": general_chat,
        }
        self.llm = _create_llm(settings.primary_model)

        logger.info(
            "SkillRouter initialized",
            extra={"skills": list(self.skills.keys())},
        )

    async def route(self, query: str, context: dict) -> SkillResult:
        """
        Classify intent and dispatch to the right skill.

        Args:
            query: User's message (cleaned)
            context: Dict with document_id, document_ids, history, mode, etc.

        Returns:
            SkillResult from whichever skill handled the query
        """
        # Determine intent
        intent = await self._classify_intent(query, context)

        logger.info(
            "Intent classified",
            extra={"intent": intent, "query": query[:50]},
        )

        # Handle "combined" — run both document_qa and fact_checker
        if intent == "combined":
            return await self._execute_combined(query, context)

        # Dispatch to the appropriate skill
        skill = self.skills.get(intent, self.skills["general"])
        return await skill.execute(query, context)

    async def _classify_intent(self, query: str, context: dict) -> str:
        """Use LLM to classify the user's intent."""
        has_documents = bool(
            context.get("document_id") or context.get("document_ids")
        )
        has_selection = has_documents

        prompt = ROUTER_PROMPT.format(
            query=query,
            has_documents=has_documents,
            has_selection=has_selection,
        )

        try:
            result = self.llm.invoke([HumanMessage(content=prompt)])
            intent = _extract_text(result.content).strip().lower().strip('"\'')

            # Validate the response
            valid_intents = ["fact_check", "document_qa", "combined", "general"]
            if intent in valid_intents:
                return intent

            # Fallback heuristics if LLM gives unexpected response
            return self._heuristic_fallback(query, context)

        except Exception as e:
            logger.warning(
                "Intent classification failed, using heuristic",
                extra={"error": str(e)},
            )
            return self._heuristic_fallback(query, context)

    def _heuristic_fallback(self, query: str, context: dict) -> str:
        """Simple keyword-based fallback if LLM classification fails."""
        query_lower = query.lower()

        # Fact-checking signals
        fact_check_signals = [
            "is it true", "is this true", "fact check", "verify",
            "is it accurate", "true or false", "real or fake",
            "misleading", "credible", "legitimate",
        ]
        if any(signal in query_lower for signal in fact_check_signals):
            return "fact_check"

        # Document signals (only if docs are selected)
        if context.get("document_id") or context.get("document_ids"):
            doc_signals = [
                "document", "pdf", "file", "chapter", "page",
                "according to", "what does it say", "in the",
            ]
            if any(signal in query_lower for signal in doc_signals):
                return "document_qa"
            # If documents are selected but no explicit signal, default to doc_qa
            return "document_qa"

        return "general"

    async def _execute_combined(self, query: str, context: dict) -> SkillResult:
        """Run both document_qa and fact_checker, merge results."""
        doc_result = await self.skills["document_qa"].execute(query, context)
        fact_result = await self.skills["fact_check"].execute(query, context)

        # Merge responses
        combined_response = (
            f"## 📄 From Your Documents\n\n{doc_result.response}\n\n"
            f"---\n\n"
            f"## ✓ Fact-Check Analysis\n\n{fact_result.response}"
        )

        # Merge sources
        all_sources = doc_result.sources + fact_result.sources

        return SkillResult(
            response=combined_response,
            skill_used="combined",
            sources=all_sources,
            metadata={
                "document_qa": doc_result.metadata,
                "fact_checker": fact_result.metadata,
            },
        )
