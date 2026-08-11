"""
Contextual Compression — Extract only the relevant parts from retrieved chunks.

The problem: Retrieved chunks are 1000 characters each. Maybe only 2 sentences
in each chunk are actually relevant to the user's question. The rest is noise
that wastes tokens and can confuse the LLM.

The solution: After retrieval, run a lightweight LLM call on each chunk to
extract ONLY the sentences that answer the question. Then pass the compressed
context (not the full chunks) to the main LLM.

Benefits:
- Fewer tokens in the final prompt → lower cost
- Less noise → better answer quality
- More room for additional chunks (you can retrieve more, compress, keep best)

This is an advanced RAG technique you already learned in langc-course
(ContextualCompressionRetriever + LLMChainExtractor).
"""

import logging
from langchain_core.documents import Document
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

from config import settings

logger = logging.getLogger("docmind")


COMPRESSION_PROMPT = """Given the following document chunk and a user question, extract ONLY the sentences that are directly relevant to answering the question. If nothing is relevant, respond with "NOT_RELEVANT".

Do NOT answer the question. Just extract the relevant text exactly as written.

Question: {question}

Document chunk:
{chunk}

Relevant text (extract only, no commentary):"""


class CompressionService:
    """
    Compresses retrieved chunks by extracting only query-relevant content.

    Trade-off: One extra LLM call per chunk (fast model, short prompt)
    in exchange for cleaner context in the main answer generation.
    """

    def __init__(self, enabled: bool = True):
        """
        Args:
            enabled: Toggle compression on/off. Off = passthrough (no extra calls).
        """
        self.enabled = enabled

        if enabled:
            # Use a fast model for compression (it's a simple extraction task)
            self.llm = ChatGoogleGenerativeAI(
                model=settings.primary_model,
                google_api_key=settings.google_api_key,
                temperature=0.0,  # Deterministic — we want exact extraction
            )

        logger.info("CompressionService initialized", extra={"enabled": enabled})

    async def compress(self, chunks: list[Document], query: str) -> list[Document]:
        """
        Compress a list of retrieved chunks by extracting only relevant content.

        Args:
            chunks: Retrieved document chunks (full text)
            query: The user's question (used to determine relevance)

        Returns:
            Compressed documents (only relevant sentences remain).
            Chunks with no relevant content are removed entirely.
        """
        if not self.enabled or not chunks:
            return chunks

        compressed = []

        for chunk in chunks:
            extracted = await self._extract_relevant(chunk.page_content, query)

            if extracted and extracted.strip() != "NOT_RELEVANT":
                # Keep the chunk but with compressed content
                compressed_doc = Document(
                    page_content=extracted.strip(),
                    metadata={
                        **chunk.metadata,
                        "compressed": True,
                        "original_length": len(chunk.page_content),
                        "compressed_length": len(extracted.strip()),
                    },
                )
                compressed.append(compressed_doc)

        compression_ratio = (
            sum(len(c.page_content) for c in compressed) /
            max(sum(len(c.page_content) for c in chunks), 1)
        )

        logger.info(
            "Chunks compressed",
            extra={
                "input_chunks": len(chunks),
                "output_chunks": len(compressed),
                "compression_ratio": f"{compression_ratio:.0%}",
            },
        )

        # If compression removed everything, fall back to original chunks
        if not compressed:
            return chunks

        return compressed

    async def _extract_relevant(self, chunk_text: str, query: str) -> str:
        """Extract relevant sentences from a single chunk."""
        try:
            prompt = COMPRESSION_PROMPT.format(question=query, chunk=chunk_text)
            result = self.llm.invoke([HumanMessage(content=prompt)])

            # Handle list content from Gemini
            content = result.content
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        parts.append(block["text"])
                    elif isinstance(block, str):
                        parts.append(block)
                return "\n".join(parts)

            return content

        except Exception as e:
            logger.warning(
                "Compression failed for chunk, keeping original",
                extra={"error": str(e)},
            )
            # On failure, return original (graceful degradation)
            return chunk_text
