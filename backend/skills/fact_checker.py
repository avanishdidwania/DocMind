"""
Fact Checker Skill — Calls nolie-agent to verify claims.

This skill integrates NoLie's LangGraph verification agent as a tool.
NoLie's agent has:
- Claim classification (statistical, historical, political, etc.)
- Source credibility check (MBFC database)
- RAG cache lookup (previously verified claims)
- Web search (Tavily) for recent events
- LLM-based verification with cross-checking
- Max 7 tool calls guardrail

We call it via its Railway endpoint: POST /verify
"""

import logging
import httpx

from skills.base import BaseSkill, SkillResult
from config import settings

logger = logging.getLogger("docmind")

NOLIE_AGENT_URL = "https://nolie-agent-production.up.railway.app"


class FactCheckerSkill(BaseSkill):
    """
    Verifies factual claims using the NoLie agent.

    The agent autonomously decides which tools to use:
    - classify_claim_type
    - check_source_credibility
    - search_verified_claims (RAG cache)
    - web_search (Tavily)
    - verify_claim_with_context
    """

    name = "fact_checker"
    description = (
        "Verify factual claims, check if something is true/false/misleading. "
        "Uses web search, source credibility analysis, and cross-verification."
    )

    def __init__(self, agent_url: str = NOLIE_AGENT_URL, timeout: float = 45.0):
        """
        Args:
            agent_url: URL of the nolie-agent service
            timeout: Request timeout (agent can take 20-30s for complex claims)
        """
        self.agent_url = agent_url
        self.timeout = timeout

    async def execute(self, query: str, context: dict) -> SkillResult:
        """
        Verify the user's claim via nolie-agent.

        Extracts the claim from the query and sends it to the verification agent.
        """
        # Extract claim — the query itself IS the claim in most cases
        claim = query
        article_context = context.get("article_context", "")
        domain = context.get("domain", "")

        try:
            result = await self._call_agent(
                claim=claim,
                context=article_context,
                domain=domain,
            )

            # Format response
            response = self._format_verdict(result)

            return SkillResult(
                response=response,
                skill_used=self.name,
                sources=result.get("tools_used", []),
                confidence=result.get("confidence", ""),
                metadata={
                    "verdict": result.get("verdict", "UNVERIFIABLE"),
                    "confidence": result.get("confidence", "LOW"),
                    "explanation": result.get("explanation", ""),
                    "reasoning_trail": result.get("reasoning_trail", []),
                    "tools_used": result.get("tools_used", []),
                },
            )

        except httpx.TimeoutException:
            logger.warning("NoLie agent timed out", extra={"claim": claim[:50]})
            return SkillResult(
                response=(
                    "The fact-checking agent took too long to respond. "
                    "This usually happens with complex claims that require multiple web searches. "
                    "Please try again or simplify the claim."
                ),
                skill_used=self.name,
                metadata={"error": "timeout"},
            )

        except httpx.ConnectError:
            logger.error("NoLie agent unreachable", extra={"url": self.agent_url})
            return SkillResult(
                response=(
                    "The fact-checking service is currently unavailable. "
                    "Please try again later."
                ),
                skill_used=self.name,
                metadata={"error": "connection_failed"},
            )

        except Exception as e:
            logger.error("Fact checker error", extra={"error": str(e)})
            return SkillResult(
                response=f"Fact-checking failed: {str(e)}",
                skill_used=self.name,
                metadata={"error": str(e)},
            )

    async def _call_agent(self, claim: str, context: str, domain: str) -> dict:
        """Call the nolie-agent /verify endpoint."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.agent_url}/verify",
                json={
                    "claim": claim,
                    "context": context[:2000],  # Limit context size
                    "domain": domain,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()

    def _format_verdict(self, result: dict) -> str:
        """Format the agent's verdict into a readable response."""
        verdict = result.get("verdict", "UNVERIFIABLE")
        confidence = result.get("confidence", "LOW")
        explanation = result.get("explanation", "No explanation provided.")
        tools_used = result.get("tools_used", [])
        reasoning = result.get("reasoning_trail", [])

        # Verdict emoji
        verdict_emoji = {
            "TRUE": "✅",
            "FALSE": "❌",
            "MISLEADING": "⚠️",
            "UNVERIFIABLE": "❓",
        }.get(verdict, "❓")

        # Confidence indicator
        confidence_bar = {
            "HIGH": "🟢 High",
            "MEDIUM": "🟡 Medium",
            "LOW": "🔴 Low",
        }.get(confidence, "🔴 Low")

        # Build response
        parts = [
            f"## {verdict_emoji} Verdict: **{verdict}**",
            f"**Confidence:** {confidence_bar}",
            f"\n**Explanation:** {explanation}",
        ]

        if tools_used:
            tools_str = ", ".join(tools_used)
            parts.append(f"\n**Verification methods used:** {tools_str}")

        if reasoning and len(reasoning) > 1:
            parts.append("\n**Reasoning trail:**")
            for i, step in enumerate(reasoning[:5], 1):
                # Truncate long reasoning steps
                step_text = step[:150] + "..." if len(step) > 150 else step
                parts.append(f"  {i}. {step_text}")

        return "\n".join(parts)

    async def health_check(self) -> bool:
        """Check if the nolie-agent is reachable."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.agent_url}/", timeout=5.0)
                return response.status_code == 200
        except Exception:
            return False
