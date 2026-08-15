"""
Evaluation Endpoint — Automated RAG quality scoring.

POST /api/evaluate/{document_id} → Generate questions, run pipeline, score results.

This shows you think about QUALITY, not just features.
"""

import logging

from fastapi import APIRouter, Request, HTTPException

router = APIRouter()
logger = logging.getLogger("docmind")


@router.post("/evaluate/{document_id}")
async def evaluate_document(request: Request, document_id: str, n_questions: int = 5):
    """
    Run automated RAG evaluation on an uploaded document.

    Generates synthetic Q&A pairs from the document, runs them through
    the full RAG pipeline, and scores:
    - Retrieval Relevance (1-5): Did we find the right chunks?
    - Answer Faithfulness (1-5): Is the answer grounded in context?

    Args:
        document_id: The document to evaluate
        n_questions: Number of test questions to generate (default: 5)

    Returns:
        Evaluation summary with per-question breakdown and aggregate scores.
    """
    doc_service = request.app.state.doc_service
    eval_service = request.app.state.eval_service

    # Verify document exists
    doc_meta = doc_service.get_document(document_id)
    if not doc_meta:
        raise HTTPException(status_code=404, detail="Document not found")

    # Get the document text (we need it for Q&A generation)
    # Use the document service's stored chunks for text reconstruction
    doc_service = request.app.state.doc_service
    retrieval = request.app.state.retrieval

    # Get chunks from the BM25 index (already stored during upload)
    doc_chunks = retrieval._doc_chunks.get(document_id, [])

    if not doc_chunks:
        # Fallback: try vector store search with a generic query
        vector_store = request.app.state.vector_store
        doc_chunks = vector_store.similarity_search(
            query="document overview summary main content",
            k=50,
            document_id=document_id,
        )

    if not doc_chunks:
        raise HTTPException(status_code=422, detail="No chunks found for document")

    # Reconstruct document text from chunks
    document_text = "\n\n".join(chunk.page_content for chunk in doc_chunks)

    # Run evaluation
    summary = await eval_service.evaluate_document(
        document_id=document_id,
        document_text=document_text,
        n_questions=min(n_questions, 10),  # Cap at 10 to limit API costs
    )

    # Format response
    return {
        "document_id": summary.document_id,
        "total_questions": summary.total_questions,
        "scores": {
            "retrieval_relevance": {
                "average": round(summary.avg_retrieval_relevance, 2),
                "max": 5.0,
                "interpretation": _interpret_score(summary.avg_retrieval_relevance),
            },
            "answer_faithfulness": {
                "average": round(summary.avg_answer_faithfulness, 2),
                "max": 5.0,
                "interpretation": _interpret_score(summary.avg_answer_faithfulness),
            },
        },
        "avg_latency_ms": round(summary.avg_latency_ms),
        "evaluation_time_ms": round(summary.evaluation_time_ms),
        "results": [
            {
                "question": r.question,
                "expected_answer": r.expected_answer,
                "actual_answer": r.actual_answer[:200],  # Truncate for readability
                "retrieval_relevance": r.retrieval_relevance,
                "answer_faithfulness": r.answer_faithfulness,
                "latency_ms": round(r.latency_ms),
            }
            for r in summary.results
        ],
    }


def _interpret_score(score: float) -> str:
    """Human-readable interpretation of a 1-5 score."""
    if score >= 4.5:
        return "Excellent"
    elif score >= 3.5:
        return "Good"
    elif score >= 2.5:
        return "Fair — consider tuning chunking or retrieval"
    elif score >= 1.5:
        return "Poor — retrieval or generation needs work"
    else:
        return "Very poor — fundamental issues to address"
