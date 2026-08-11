"""
Vector Store Abstraction — Chroma for dev, PGVector for prod.

This wraps the vector database with a clean interface:
- add_documents(): embed and store chunks
- similarity_search(): find relevant chunks for a query
- delete_document(): remove all chunks for a document

Why an abstraction:
- Dev: Chroma (in-memory, zero setup, instant)
- Prod: PGVector on Supabase (persistent, scalable, HNSW indexes)
- Same interface — swap with one config change, no code changes.

Selection: controlled by DATABASE_URL in config.
- If DATABASE_URL starts with "postgresql://" → PGVector
- Otherwise → Chroma (in-memory fallback)
"""

import logging
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from config import settings

logger = logging.getLogger("docmind")


class VectorStore:
    """
    Vector store with a consistent interface.
    Auto-selects backend based on DATABASE_URL configuration.
    """

    def __init__(self):
        """Initialize embeddings and select the vector store backend."""
        # Embeddings model — shared across all operations
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model=settings.embedding_model,
            google_api_key=settings.google_api_key,
        )

        # Track which document_ids have been stored (for deletion)
        self._document_ids: dict[str, list[str]] = {}  # doc_id → [chunk_ids]

        # Select backend based on config
        self._backend_name = self._select_backend()

    def _select_backend(self) -> str:
        """
        Auto-select backend based on DATABASE_URL.

        PostgreSQL URL detected → PGVector (production)
        Otherwise → Chroma in-memory (development)
        """
        db_url = settings.database_url

        if db_url and db_url.startswith("postgresql"):
            return self._init_pgvector(db_url)
        else:
            return self._init_chroma()

    def _init_chroma(self) -> str:
        """Initialize Chroma in-memory backend (development)."""
        from langchain_chroma import Chroma

        self._store = Chroma(
            collection_name="docmind_chunks",
            embedding_function=self.embeddings,
        )

        logger.info(
            "VectorStore initialized",
            extra={"backend": "chroma_memory", "embedding_model": settings.embedding_model},
        )
        return "chroma"

    def _init_pgvector(self, db_url: str) -> str:
        """
        Initialize PGVector backend (production).

        PGVector advantages over Chroma:
        - Persistent (survives restarts)
        - Scalable (handles millions of vectors)
        - HNSW indexes (O(log n) search, not O(n))
        - Shared across instances (horizontal scaling)
        - Managed by Supabase (backups, monitoring)
        """
        try:
            from langchain_postgres import PGVector

            self._store = PGVector(
                embeddings=self.embeddings,
                connection=db_url,
                collection_name="docmind_chunks",
                use_jsonb=True,  # Store metadata as JSONB (filterable)
            )

            logger.info(
                "VectorStore initialized",
                extra={
                    "backend": "pgvector",
                    "embedding_model": settings.embedding_model,
                    "connection": db_url[:30] + "...",  # Don't log full URL (has password)
                },
            )
            return "pgvector"

        except Exception as e:
            # If PGVector fails to connect, fall back to Chroma
            logger.warning(
                "PGVector connection failed, falling back to Chroma",
                extra={"error": str(e)},
            )
            return self._init_chroma()

    def add_documents(self, documents: list[Document], document_id: str) -> list[str]:
        """
        Embed and store documents in the vector database.

        Args:
            documents: LangChain Document objects with page_content + metadata
            document_id: Parent document ID (for grouping/deletion)

        Returns:
            List of chunk IDs assigned by the store
        """
        ids = self._store.add_documents(documents)

        # Track for deletion
        self._document_ids[document_id] = ids

        logger.info(
            "Documents stored in vector DB",
            extra={
                "document_id": document_id,
                "chunks_stored": len(ids),
                "backend": self._backend_name,
            },
        )

        return ids

    def similarity_search(
        self,
        query: str,
        k: int = 4,
        document_id: str | None = None,
    ) -> list[Document]:
        """
        Find the most relevant chunks for a query.

        Args:
            query: The search query (will be embedded automatically)
            k: Number of results to return
            document_id: If provided, only search within this document

        Returns:
            List of relevant Document objects (page_content + metadata)
        """
        filter_dict = None
        if document_id:
            filter_dict = {"document_id": document_id}

        results = self._store.similarity_search(
            query,
            k=k,
            filter=filter_dict,
        )

        return results

    def similarity_search_with_scores(
        self,
        query: str,
        k: int = 4,
        document_id: str | None = None,
    ) -> list[tuple[Document, float]]:
        """
        Search with relevance scores (useful for filtering low-quality results).
        """
        filter_dict = None
        if document_id:
            filter_dict = {"document_id": document_id}

        return self._store.similarity_search_with_score(
            query,
            k=k,
            filter=filter_dict,
        )

    def delete_document(self, document_id: str) -> bool:
        """
        Delete all chunks belonging to a document.
        """
        if document_id not in self._document_ids:
            return False

        chunk_ids = self._document_ids[document_id]
        self._store.delete(ids=chunk_ids)
        del self._document_ids[document_id]

        logger.info(
            "Document chunks deleted",
            extra={"document_id": document_id, "chunks_deleted": len(chunk_ids)},
        )

        return True

    @property
    def backend(self) -> str:
        """Which backend is active: 'chroma' or 'pgvector'."""
        return self._backend_name

    @property
    def total_chunks(self) -> int:
        """Total number of chunks stored across all documents."""
        return sum(len(ids) for ids in self._document_ids.values())

    @property
    def document_count(self) -> int:
        """Number of documents in the store."""
        return len(self._document_ids)
