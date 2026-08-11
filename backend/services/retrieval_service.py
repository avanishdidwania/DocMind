"""
Retrieval Service — The "R" in RAG.

Given a user query and a document_id:
1. Search BOTH vector store (semantic) AND BM25 (keyword)
2. Combine results with Reciprocal Rank Fusion (RRF)
3. Format into context for the LLM prompt
4. Return the formatted context + source references

Hybrid retrieval solves a real problem:
- Vector search is great for semantic queries ("how does auth work?")
- BM25 is great for exact terms ("error code E_CONN_REFUSED", "SKU-7742X")
- Combining both with RRF gives you the best of both worlds.

You already built this in langc-course (prod_hybridsearch.py) — now it's
integrated into a real production system.
"""

import logging
from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_community.retrievers import BM25Retriever

from db.vector_store import VectorStore

logger = logging.getLogger("docmind")


@dataclass
class RetrievalResult:
    """Result of a retrieval operation."""
    context: str                  # Formatted text to inject into LLM prompt
    sources: list[str]            # Source references (filename + chunk index)
    chunks_retrieved: int         # How many chunks were found
    has_context: bool             # Whether any relevant context was found


class RetrievalService:
    """
    Hybrid retrieval: BM25 (keyword) + Vector (semantic) combined with RRF.

    Initialized once, shared via app.state.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        k: int = 4,
        bm25_weight: float = 0.4,
        vector_weight: float = 0.6,
        rrf_k: int = 60,
    ):
        """
        Args:
            vector_store: The vector store for semantic search
            k: Number of final results to return
            bm25_weight: Weight for BM25 results in RRF (keyword matching)
            vector_weight: Weight for vector results in RRF (semantic matching)
            rrf_k: RRF constant (higher = more even blending, 60 is standard)
        """
        self.vector_store = vector_store
        self.k = k
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight
        self.rrf_k = rrf_k

        # BM25 indexes per document (built on first query per doc)
        self._bm25_indexes: dict[str, BM25Retriever] = {}
        # Track which documents have chunks stored (for BM25 building)
        self._doc_chunks: dict[str, list[Document]] = {}

        logger.info(
            "RetrievalService initialized (hybrid: BM25 + Vector + RRF)",
            extra={
                "k": k,
                "bm25_weight": bm25_weight,
                "vector_weight": vector_weight,
                "rrf_k": rrf_k,
            },
        )

    def register_chunks(self, document_id: str, chunks: list[Document]) -> None:
        """
        Register document chunks for BM25 indexing.
        Called after a document is processed.
        """
        self._doc_chunks[document_id] = chunks
        # Build BM25 index for this document
        if chunks:
            self._bm25_indexes[document_id] = BM25Retriever.from_documents(
                chunks, k=self.k
            )
            logger.info(
                "BM25 index built",
                extra={"document_id": document_id, "chunks": len(chunks)},
            )

    def remove_document(self, document_id: str) -> None:
        """Remove a document's BM25 index."""
        self._bm25_indexes.pop(document_id, None)
        self._doc_chunks.pop(document_id, None)

    def retrieve(self, query: str, document_id: str | None = None) -> RetrievalResult:
        """
        Hybrid retrieval: combine BM25 + Vector search with RRF.

        If BM25 index exists for the document, uses hybrid.
        Otherwise falls back to vector-only (still works, just no keyword boost).
        """
        # Vector search (semantic)
        vector_results = self.vector_store.similarity_search(
            query=query,
            k=self.k,
            document_id=document_id,
        )

        # BM25 search (keyword) — if we have an index for this document
        bm25_results = []
        if document_id and document_id in self._bm25_indexes:
            try:
                bm25_results = self._bm25_indexes[document_id].invoke(query)
            except Exception as e:
                logger.warning(
                    "BM25 search failed, using vector-only",
                    extra={"document_id": document_id, "error": str(e)},
                )

        # If we have both, combine with RRF
        if bm25_results and vector_results:
            combined = self._reciprocal_rank_fusion(
                retrievers_results=[vector_results, bm25_results],
                weights=[self.vector_weight, self.bm25_weight],
            )
            logger.info(
                "Hybrid retrieval (BM25 + Vector + RRF)",
                extra={
                    "vector_results": len(vector_results),
                    "bm25_results": len(bm25_results),
                    "combined_results": len(combined),
                },
            )
        elif vector_results:
            combined = vector_results[:self.k]
        else:
            combined = []

        if not combined:
            return RetrievalResult(
                context="",
                sources=[],
                chunks_retrieved=0,
                has_context=False,
            )

        # Format context for the LLM
        context = self._format_context(combined)
        sources = self._extract_sources(combined)

        return RetrievalResult(
            context=context,
            sources=sources,
            chunks_retrieved=len(combined),
            has_context=True,
        )

    def _reciprocal_rank_fusion(
        self,
        retrievers_results: list[list[Document]],
        weights: list[float],
    ) -> list[Document]:
        """
        Reciprocal Rank Fusion — combines multiple ranked lists into one.

        How it works:
        - For each document in each result list:
          score = weight * (1 / (rank + rrf_k))
        - Sum scores across all retrievers for the same document
        - Sort by total score (highest first)

        Why RRF over simple interleaving:
        - Handles different score scales (BM25 scores vs cosine similarity)
        - Rank-based, not score-based (no normalization needed)
        - Documents that appear in BOTH lists get boosted (good signal)
        """
        doc_scores: dict[str, tuple[float, Document]] = {}

        for results, weight in zip(retrievers_results, weights):
            for rank, doc in enumerate(results):
                key = doc.page_content  # Use content as dedup key
                rrf_score = weight * (1.0 / (rank + self.rrf_k))

                if key in doc_scores:
                    existing_score, existing_doc = doc_scores[key]
                    doc_scores[key] = (existing_score + rrf_score, existing_doc)
                else:
                    doc_scores[key] = (rrf_score, doc)

        # Sort by RRF score (highest first)
        sorted_docs = sorted(doc_scores.values(), key=lambda x: x[0], reverse=True)

        return [doc for _, doc in sorted_docs[:self.k]]

    def _format_context(self, chunks: list[Document]) -> str:
        """Format retrieved chunks into a context string for the LLM."""
        formatted_parts = []

        for i, chunk in enumerate(chunks, 1):
            source = chunk.metadata.get("filename", "unknown")
            chunk_idx = chunk.metadata.get("chunk_index", "?")

            formatted_parts.append(
                f"[Source {i}: {source}, chunk {chunk_idx}]\n{chunk.page_content}"
            )

        return "\n\n---\n\n".join(formatted_parts)

    def _extract_sources(self, chunks: list[Document]) -> list[str]:
        """Extract source references from chunk metadata."""
        sources = []
        seen = set()

        for chunk in chunks:
            filename = chunk.metadata.get("filename", "unknown")
            chunk_idx = chunk.metadata.get("chunk_index", "?")
            ref = f"{filename} (chunk {chunk_idx})"

            if ref not in seen:
                sources.append(ref)
                seen.add(ref)

        return sources
