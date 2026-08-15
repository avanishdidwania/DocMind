"""
Retrieval Service — The "R" in RAG.

Given a user query and a document_id:
1. Search BOTH vector store (semantic) AND BM25 (keyword)
2. Combine results with Reciprocal Rank Fusion (RRF)
3. SELF-CORRECT: Grade retrieval quality. If poor, reformulate query and retry.
4. Format into context for the LLM prompt
5. Return the formatted context + source references

Self-correcting retrieval (Agentic RAG):
- After retrieval, an LLM grades: "Do these chunks answer the question?"
- If YES → proceed to generation
- If NO → reformulate the query (rephrase, expand, decompose) and retrieve again
- Max 2 attempts to avoid infinite loops

This is what separates "dumb retrieval" from "intelligent retrieval."
"""

import logging
from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage
from langchain_community.retrievers import BM25Retriever

from db.vector_store import VectorStore
from config import settings

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
    Optional contextual compression to reduce noise before passing to LLM.
    Self-correcting: grades retrieval quality, reformulates and retries if poor.

    Initialized once, shared via app.state.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        compression_service=None,
        k: int = 4,
        bm25_weight: float = 0.4,
        vector_weight: float = 0.6,
        rrf_k: int = 60,
        max_retrieval_attempts: int = 2,
    ):
        """
        Args:
            vector_store: The vector store for semantic search
            compression_service: Optional contextual compression (extracts relevant parts)
            k: Number of final results to return
            bm25_weight: Weight for BM25 results in RRF (keyword matching)
            vector_weight: Weight for vector results in RRF (semantic matching)
            rrf_k: RRF constant (higher = more even blending, 60 is standard)
            max_retrieval_attempts: Max times to reformulate and retry (self-correcting)
        """
        self.vector_store = vector_store
        self.compression = compression_service
        self.k = k
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight
        self.rrf_k = rrf_k
        self.max_retrieval_attempts = max_retrieval_attempts

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

    async def retrieve(self, query: str, document_id: str | None = None) -> RetrievalResult:
        """
        Hybrid retrieval: combine BM25 + Vector search with RRF.
        Optionally compresses results to extract only relevant parts.

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

        # Contextual compression (extract only relevant parts)
        if self.compression:
            combined = await self.compression.compress(combined, query)

        # Format context for the LLM
        context = self._format_context(combined)
        sources = self._extract_sources(combined)

        return RetrievalResult(
            context=context,
            sources=sources,
            chunks_retrieved=len(combined),
            has_context=True,
        )

    async def retrieve_multi(self, query: str, document_ids: list[str]) -> RetrievalResult:
        """
        Retrieve across multiple documents simultaneously.

        Use case: "Compare what document A says about X vs document B."
        Searches each document, combines all results with RRF, returns unified context.
        """
        all_vector_results = []
        all_bm25_results = []

        for doc_id in document_ids:
            # Vector search per document
            vector_results = self.vector_store.similarity_search(
                query=query,
                k=self.k,
                document_id=doc_id,
            )
            all_vector_results.extend(vector_results)

            # BM25 per document (if index exists)
            if doc_id in self._bm25_indexes:
                try:
                    bm25_results = self._bm25_indexes[doc_id].invoke(query)
                    all_bm25_results.extend(bm25_results)
                except Exception:
                    pass

        if not all_vector_results and not all_bm25_results:
            return RetrievalResult(
                context="",
                sources=[],
                chunks_retrieved=0,
                has_context=False,
            )

        # Combine with RRF
        if all_bm25_results and all_vector_results:
            combined = self._reciprocal_rank_fusion(
                retrievers_results=[all_vector_results, all_bm25_results],
                weights=[self.vector_weight, self.bm25_weight],
            )
        else:
            combined = all_vector_results[:self.k]

        # Contextual compression
        if self.compression:
            combined = await self.compression.compress(combined, query)

        context = self._format_context(combined)
        sources = self._extract_sources(combined)

        logger.info(
            "Multi-document retrieval",
            extra={
                "document_ids": document_ids,
                "chunks_retrieved": len(combined),
            },
        )

        return RetrievalResult(
            context=context,
            sources=sources,
            chunks_retrieved=len(combined),
            has_context=True,
        )

    # ─── Self-Correcting Retrieval (Agentic RAG) ───────────────────────

    async def retrieve_with_correction(
        self, query: str, document_id: str | None = None
    ) -> RetrievalResult:
        """
        Self-correcting retrieval: retrieve → grade → reformulate if needed → retry.

        This is the AGENTIC part of our RAG:
        1. Retrieve chunks normally (hybrid search)
        2. Ask an LLM: "Do these chunks contain enough info to answer the question?"
        3. If YES → return the chunks (proceed to generation)
        4. If NO → ask LLM to reformulate the query, then retrieve again
        5. Max attempts = max_retrieval_attempts (default 2)

        Falls back to regular retrieval if grading/reformulation fails.
        """
        from agent.graph import _create_llm, _extract_text

        current_query = query
        attempt = 0

        while attempt < self.max_retrieval_attempts:
            attempt += 1

            # Step 1: Retrieve with current query
            result = await self._do_retrieval(current_query, document_id)

            if not result.has_context:
                # Nothing found at all — try reformulating
                if attempt < self.max_retrieval_attempts:
                    reformulated = await self._reformulate_query(query, current_query)
                    if reformulated and reformulated != current_query:
                        logger.info(
                            "Self-correcting: no context found, reformulating",
                            extra={
                                "attempt": attempt,
                                "original": current_query[:50],
                                "reformulated": reformulated[:50],
                            },
                        )
                        current_query = reformulated
                        continue
                return result

            # Step 2: Grade the retrieval quality
            is_relevant = await self._grade_retrieval(query, result.context)

            if is_relevant:
                # Chunks are good enough — proceed
                logger.info(
                    "Self-correcting: retrieval graded as RELEVANT",
                    extra={"attempt": attempt, "query": query[:50]},
                )
                return result

            # Step 3: Not relevant enough — reformulate and retry
            if attempt < self.max_retrieval_attempts:
                reformulated = await self._reformulate_query(query, current_query)
                if reformulated and reformulated != current_query:
                    logger.info(
                        "Self-correcting: retrieval graded as POOR, reformulating",
                        extra={
                            "attempt": attempt,
                            "original": current_query[:50],
                            "reformulated": reformulated[:50],
                        },
                    )
                    current_query = reformulated
                else:
                    # Can't reformulate differently — return what we have
                    return result
            else:
                # Max attempts reached — return best effort
                return result

        return result

    async def _grade_retrieval(self, query: str, context: str) -> bool:
        """
        Ask an LLM: "Does this context contain enough info to answer the question?"
        Returns True if relevant, False if not.
        """
        from agent.graph import _create_llm, _extract_text

        try:
            llm = _create_llm(settings.primary_model)

            grading_prompt = (
                f"You are a retrieval quality grader. Your job is to determine if the "
                f"retrieved context contains enough information to answer the user's question.\n\n"
                f"Question: {query}\n\n"
                f"Retrieved Context:\n{context[:2000]}\n\n"
                f"Does this context contain sufficient information to answer the question? "
                f"Respond with ONLY 'YES' or 'NO'."
            )

            result = llm.invoke([HumanMessage(content=grading_prompt)])
            answer = _extract_text(result.content).strip().upper()

            return "YES" in answer

        except Exception as e:
            logger.warning(
                "Retrieval grading failed, assuming relevant",
                extra={"error": str(e)},
            )
            # On failure, don't block — assume relevant and proceed
            return True

    async def _reformulate_query(self, original_query: str, last_query: str) -> str:
        """
        Ask an LLM to reformulate the query for better retrieval.
        Strategies: rephrase, expand with synonyms, decompose into sub-questions.
        """
        from agent.graph import _create_llm, _extract_text

        try:
            llm = _create_llm(settings.primary_model)

            reformulation_prompt = (
                f"The following search query did not retrieve relevant results from a document database. "
                f"Please reformulate it to improve retrieval. Try these strategies:\n"
                f"- Use different keywords or synonyms\n"
                f"- Make it more specific or more general\n"
                f"- Break it into a clearer, more searchable phrase\n\n"
                f"Original question: {original_query}\n"
                f"Last search query tried: {last_query}\n\n"
                f"Provide ONLY the reformulated search query, nothing else:"
            )

            result = llm.invoke([HumanMessage(content=reformulation_prompt)])
            reformulated = _extract_text(result.content).strip()

            # Clean up — remove quotes if the LLM wrapped it
            reformulated = reformulated.strip('"\'')

            return reformulated if reformulated else last_query

        except Exception as e:
            logger.warning(
                "Query reformulation failed",
                extra={"error": str(e)},
            )
            return last_query

    async def _do_retrieval(self, query: str, document_id: str | None) -> RetrievalResult:
        """Execute a single retrieval pass (hybrid search + optional compression)."""
        # Vector search (semantic)
        vector_results = self.vector_store.similarity_search(
            query=query,
            k=self.k,
            document_id=document_id,
        )

        # BM25 search (keyword)
        bm25_results = []
        if document_id and document_id in self._bm25_indexes:
            try:
                bm25_results = self._bm25_indexes[document_id].invoke(query)
            except Exception:
                pass

        # Combine with RRF
        if bm25_results and vector_results:
            combined = self._reciprocal_rank_fusion(
                retrievers_results=[vector_results, bm25_results],
                weights=[self.vector_weight, self.bm25_weight],
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

        # Contextual compression
        if self.compression:
            combined = await self.compression.compress(combined, query)

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
