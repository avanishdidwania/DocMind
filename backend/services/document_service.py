"""
Document Service — The ingestion pipeline.

Flow: PDF File → Extract Text → Chunk → Embed → Store in Vector DB

This is the "indexing" side of RAG:
1. User uploads a PDF
2. We extract raw text (page by page)
3. We split into chunks (RecursiveCharacterTextSplitter)
4. We embed each chunk and store in the vector database
5. Document metadata is tracked for management (list, delete)

The retrieval side (query time) is in retrieval_service.py.
"""

import uuid
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

logger = logging.getLogger("docmind")


# ─── Document Metadata ──────────────────────────────────────────────────────


@dataclass
class DocumentMetadata:
    """Tracks an uploaded document and its processing state."""
    document_id: str
    filename: str
    page_count: int
    chunk_count: int
    total_characters: int
    processing_time_ms: float
    created_at: float = field(default_factory=time.time)


# ─── Document Service ───────────────────────────────────────────────────────


class DocumentService:
    """
    Handles the full document ingestion pipeline.

    Initialized once at startup, shared across requests via app.state.
    """

    def __init__(self, vector_store, retrieval_service=None, chunk_size: int = 1000, chunk_overlap: int = 200):
        """
        Args:
            vector_store: The vector store instance (Chroma or PGVector)
            retrieval_service: The retrieval service (for BM25 registration)
            chunk_size: Characters per chunk (1000 is a good balance)
            chunk_overlap: Overlap between chunks (preserves context at boundaries)
        """
        self.vector_store = vector_store
        self.retrieval_service = retrieval_service
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
            length_function=len,
        )

        # In-memory document registry (tracks what's been uploaded)
        # Production: this would be a database table
        self._documents: dict[str, DocumentMetadata] = {}

        logger.info(
            "DocumentService initialized",
            extra={"chunk_size": chunk_size, "chunk_overlap": chunk_overlap},
        )

    # ─── Core Pipeline ──────────────────────────────────────────────────

    async def process_pdf(self, file_content: bytes, filename: str) -> DocumentMetadata:
        """
        Full pipeline: PDF bytes → extracted text → chunks → vector store.

        Args:
            file_content: Raw bytes of the uploaded PDF
            filename: Original filename (for metadata)

        Returns:
            DocumentMetadata with processing stats
        """
        start = time.time()
        document_id = str(uuid.uuid4())[:12]

        # Step 1: Extract text from PDF
        pages_text = self._extract_text(file_content)
        total_text = "\n\n".join(pages_text)

        logger.info(
            "PDF text extracted",
            extra={
                "document_id": document_id,
                "file_name": filename,
                "pages": len(pages_text),
                "characters": len(total_text),
            },
        )

        # Step 2: Chunk the text
        chunks = self._chunk_text(total_text, document_id, filename)

        # Step 3: Store in vector database
        await self._store_chunks(chunks, document_id)

        # Step 4: Record metadata
        processing_time = (time.time() - start) * 1000

        metadata = DocumentMetadata(
            document_id=document_id,
            filename=filename,
            page_count=len(pages_text),
            chunk_count=len(chunks),
            total_characters=len(total_text),
            processing_time_ms=processing_time,
        )

        self._documents[document_id] = metadata

        logger.info(
            "Document processed successfully",
            extra={
                "document_id": document_id,
                "chunks": len(chunks),
                "processing_ms": processing_time,
            },
        )

        return metadata

    # ─── Text Extraction ────────────────────────────────────────────────

    def _extract_text(self, file_content: bytes) -> list[str]:
        """
        Extract text from PDF, page by page.
        Uses PyPDF — lightweight, pure Python, no system dependencies.
        """
        import io

        reader = PdfReader(io.BytesIO(file_content))
        pages = []

        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text and text.strip():
                pages.append(text.strip())

        if not pages:
            raise ValueError("Could not extract any text from the PDF")

        return pages

    # ─── Chunking ───────────────────────────────────────────────────────

    def _chunk_text(
        self, text: str, document_id: str, filename: str
    ) -> list[Document]:
        """
        Split text into chunks with metadata.

        Each chunk becomes a LangChain Document with:
        - page_content: the actual text
        - metadata: document_id, filename, chunk_index (for tracing back to source)
        """
        raw_chunks = self.splitter.split_text(text)

        documents = []
        for i, chunk_text in enumerate(raw_chunks):
            doc = Document(
                page_content=chunk_text,
                metadata={
                    "document_id": document_id,
                    "filename": filename,
                    "chunk_index": i,
                    "total_chunks": len(raw_chunks),
                },
            )
            documents.append(doc)

        return documents

    # ─── Vector Storage ─────────────────────────────────────────────────

    async def _store_chunks(self, chunks: list[Document], document_id: str) -> None:
        """
        Embed and store chunks in the vector database.
        Also registers chunks with the retrieval service for BM25 indexing.
        """
        self.vector_store.add_documents(chunks, document_id=document_id)

        # Register with retrieval service for hybrid (BM25) search
        if self.retrieval_service:
            self.retrieval_service.register_chunks(document_id, chunks)

    # ─── Document Management ────────────────────────────────────────────

    def list_documents(self) -> list[dict]:
        """List all uploaded documents with metadata."""
        return [
            {
                "document_id": meta.document_id,
                "filename": meta.filename,
                "page_count": meta.page_count,
                "chunk_count": meta.chunk_count,
                "total_characters": meta.total_characters,
                "processing_time_ms": meta.processing_time_ms,
            }
            for meta in self._documents.values()
        ]

    def get_document(self, document_id: str) -> DocumentMetadata | None:
        """Get metadata for a specific document."""
        return self._documents.get(document_id)

    async def delete_document(self, document_id: str) -> bool:
        """
        Delete a document and its chunks from the vector store.
        Returns True if found and deleted, False if not found.
        """
        if document_id not in self._documents:
            return False

        # Remove from vector store
        self.vector_store.delete_document(document_id)

        # Remove from retrieval service (BM25 index)
        if self.retrieval_service:
            self.retrieval_service.remove_document(document_id)

        # Remove from registry
        del self._documents[document_id]

        logger.info("Document deleted", extra={"document_id": document_id})
        return True
