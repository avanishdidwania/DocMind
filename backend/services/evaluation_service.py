"""
Evaluation Pipeline — Automated RAG quality scoring.

Most RAG tutorials build a system and never measure if it's actually good.
This service answers: "Is my RAG pipeline working well?"

Two scores measured:
1. Retrieval Relevance — Did we find the RIGHT chunks for the question?
2. Answer Faithfulness — Is the answer GROUNDED in the retrieved context (no hallucination)?

How it works:
1. Generate synthetic Q&A pairs from the document (LLM creates questions + expected answers)
2. Run each question through the RAG pipeline
3. Score retrieval relevance (does the context contain info needed to answer?)
4. Score faithfulness (is the answer supported by the context, or hallucinated?)
5. Return aggregate scores + per-question breakdown

Use case: Run after uploading a new document to verify quality.
          Run after changing chunking/retrieval parameters to compare.
"""

import logging
import time
from dataclasses import dataclass

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

from config import settings
from services.retrieval_service import RetrievalService
from agent.graph import ProductionAgent, _extract_text

logger = logging.getLogger("docmind")


# ─── Evaluation Prompts ─────────────────────────────────────────────────────

QA_GENERATION_PROMPT = """Given the following document text, generate {n} question-answer pairs that test understanding of the content.

Requirements:
- Questions should be specific and answerable from the text
- Include a mix of factual questions and conceptual questions
- Answers should be concise (1-2 sentences)

Document text:
{text}

Respond in this exact format (one per line):
Q: <question>
A: <expected answer>
Q: <question>
A: <expected answer>
..."""

RELEVANCE_PROMPT = """Rate how relevant the retrieved context is for answering the question.
Score 1-5:
1 = Completely irrelevant
2 = Slightly related but missing key info
3 = Partially relevant, some useful info
4 = Mostly relevant, contains most needed info
5 = Perfectly relevant, contains everything needed

Question: {question}

Retrieved Context:
{context}

Respond with ONLY a number (1-5):"""

FAITHFULNESS_PROMPT = """Rate how faithful (grounded) the answer is to the provided context.
Score 1-5:
1 = Completely hallucinated, not supported by context
2 = Mostly hallucinated with minor context support
3 = Partially supported, some claims not in context
4 = Mostly faithful, nearly all claims supported
5 = Completely faithful, every claim is in the context

Context:
{context}

Question: {question}

Answer: {answer}

Respond with ONLY a number (1-5):"""


# ─── Data Models ────────────────────────────────────────────────────────────


@dataclass
class QAPair:
    """A generated question-answer pair for evaluation."""
    question: str
    expected_answer: str


@dataclass
class EvalResult:
    """Result of evaluating a single Q&A pair."""
    question: str
    expected_answer: str
    actual_answer: str
    retrieval_relevance: float  # 1-5
    answer_faithfulness: float  # 1-5
    latency_ms: float


@dataclass
class EvalSummary:
    """Aggregate evaluation results for a document."""
    document_id: str
    total_questions: int
    avg_retrieval_relevance: float
    avg_answer_faithfulness: float
    avg_latency_ms: float
    results: list[EvalResult]
    evaluation_time_ms: float


# ─── Evaluation Service ─────────────────────────────────────────────────────


class EvaluationService:
    """
    Automated RAG quality evaluation.

    Generates questions from a document, runs them through the pipeline,
    and scores retrieval relevance + answer faithfulness.
    """

    def __init__(self, retrieval_service: RetrievalService, agent: ProductionAgent):
        self.retrieval = retrieval_service
        self.agent = agent
        self.llm = ChatGoogleGenerativeAI(
            model=settings.primary_model,
            google_api_key=settings.google_api_key,
            temperature=0.0,
        )
        logger.info("EvaluationService initialized")

    async def evaluate_document(
        self,
        document_id: str,
        document_text: str,
        n_questions: int = 5,
    ) -> EvalSummary:
        """
        Run full evaluation on a document.

        Args:
            document_id: ID of the uploaded document
            document_text: Full text of the document (for Q&A generation)
            n_questions: Number of test questions to generate

        Returns:
            EvalSummary with per-question scores and aggregates
        """
        start = time.time()

        # Step 1: Generate Q&A pairs from the document
        qa_pairs = await self._generate_qa_pairs(document_text, n_questions)

        if not qa_pairs:
            return EvalSummary(
                document_id=document_id,
                total_questions=0,
                avg_retrieval_relevance=0.0,
                avg_answer_faithfulness=0.0,
                avg_latency_ms=0.0,
                results=[],
                evaluation_time_ms=(time.time() - start) * 1000,
            )

        # Step 2: Run each question through the RAG pipeline and score
        results = []
        for qa in qa_pairs:
            result = await self._evaluate_single(qa, document_id)
            results.append(result)

        # Step 3: Aggregate scores
        avg_relevance = sum(r.retrieval_relevance for r in results) / len(results)
        avg_faithfulness = sum(r.answer_faithfulness for r in results) / len(results)
        avg_latency = sum(r.latency_ms for r in results) / len(results)

        eval_time = (time.time() - start) * 1000

        logger.info(
            "Evaluation complete",
            extra={
                "document_id": document_id,
                "questions": len(results),
                "avg_relevance": f"{avg_relevance:.2f}/5",
                "avg_faithfulness": f"{avg_faithfulness:.2f}/5",
                "eval_time_ms": eval_time,
            },
        )

        return EvalSummary(
            document_id=document_id,
            total_questions=len(results),
            avg_retrieval_relevance=avg_relevance,
            avg_answer_faithfulness=avg_faithfulness,
            avg_latency_ms=avg_latency,
            results=results,
            evaluation_time_ms=eval_time,
        )

    async def _generate_qa_pairs(self, text: str, n: int) -> list[QAPair]:
        """Generate synthetic question-answer pairs from document text."""
        try:
            # Truncate text if too long (stay within token limits)
            max_chars = 6000
            truncated = text[:max_chars] if len(text) > max_chars else text

            prompt = QA_GENERATION_PROMPT.format(n=n, text=truncated)
            result = self.llm.invoke([HumanMessage(content=prompt)])
            content = _extract_text(result.content)

            # Parse Q&A pairs
            pairs = []
            lines = content.strip().split("\n")
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                if line.startswith("Q:"):
                    question = line[2:].strip()
                    # Look for the answer on the next line
                    if i + 1 < len(lines) and lines[i + 1].strip().startswith("A:"):
                        answer = lines[i + 1].strip()[2:].strip()
                        pairs.append(QAPair(question=question, expected_answer=answer))
                        i += 2
                        continue
                i += 1

            logger.info(f"Generated {len(pairs)} Q&A pairs for evaluation")
            return pairs[:n]  # Cap at requested number

        except Exception as e:
            logger.error(f"Q&A generation failed: {e}")
            return []

    async def _evaluate_single(self, qa: QAPair, document_id: str) -> EvalResult:
        """Evaluate a single question through the full RAG pipeline."""
        start = time.time()

        # Run retrieval
        retrieval_result = await self.retrieval.retrieve(
            query=qa.question,
            document_id=document_id,
        )
        context = retrieval_result.context

        # Run agent (generate answer)
        agent_result = await self.agent.invoke(query=qa.question, context=context)
        actual_answer = agent_result.get("response", "No response")

        latency = (time.time() - start) * 1000

        # Score retrieval relevance
        relevance_score = await self._score_relevance(qa.question, context)

        # Score answer faithfulness
        faithfulness_score = await self._score_faithfulness(
            qa.question, context, actual_answer
        )

        return EvalResult(
            question=qa.question,
            expected_answer=qa.expected_answer,
            actual_answer=actual_answer,
            retrieval_relevance=relevance_score,
            answer_faithfulness=faithfulness_score,
            latency_ms=latency,
        )

    async def _score_relevance(self, question: str, context: str) -> float:
        """Score how relevant the retrieved context is (1-5)."""
        if not context:
            return 1.0

        try:
            prompt = RELEVANCE_PROMPT.format(question=question, context=context[:3000])
            result = self.llm.invoke([HumanMessage(content=prompt)])
            score_text = _extract_text(result.content).strip()
            score = float(score_text)
            return max(1.0, min(5.0, score))
        except (ValueError, Exception):
            return 3.0  # Default middle score on failure

    async def _score_faithfulness(
        self, question: str, context: str, answer: str
    ) -> float:
        """Score how faithful the answer is to the context (1-5)."""
        if not context or not answer:
            return 1.0

        try:
            prompt = FAITHFULNESS_PROMPT.format(
                question=question, context=context[:3000], answer=answer[:1000]
            )
            result = self.llm.invoke([HumanMessage(content=prompt)])
            score_text = _extract_text(result.content).strip()
            score = float(score_text)
            return max(1.0, min(5.0, score))
        except (ValueError, Exception):
            return 3.0  # Default middle score on failure
