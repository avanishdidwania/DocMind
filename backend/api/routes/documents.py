"""
Document Endpoints — Upload, list, delete documents.

POST /api/documents/upload  → Upload a PDF, process it, store chunks
GET  /api/documents         → List all uploaded documents
GET  /api/documents/{id}    → Get details for a specific document
DELETE /api/documents/{id}  → Delete a document and its chunks
"""

import logging

from fastapi import APIRouter, Request, UploadFile, File, HTTPException

from models.schemas import DocumentUploadResponse

router = APIRouter()
logger = logging.getLogger("docmind")

# Max file size: 20MB
MAX_FILE_SIZE = 20 * 1024 * 1024


@router.post("/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(request: Request, file: UploadFile = File(...)):
    """
    Upload a PDF document for processing.

    Pipeline: PDF → extract text → chunk → embed → store in vector DB.
    After upload, you can chat with this document using its document_id.
    """
    doc_service = request.app.state.doc_service

    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Read file content
    content = await file.read()

    # Validate file size
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB",
        )

    # Validate not empty
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="File is empty")

    # Process the PDF
    try:
        metadata = await doc_service.process_pdf(content, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(
            "Document processing failed",
            extra={"file_name": file.filename, "error": str(e)},
        )
        raise HTTPException(status_code=500, detail="Failed to process document")

    logger.info(
        "Document uploaded and processed",
        extra={
            "document_id": metadata.document_id,
            "file_name": metadata.filename,
            "chunks": metadata.chunk_count,
        },
    )

    return DocumentUploadResponse(
        document_id=metadata.document_id,
        filename=metadata.filename,
        page_count=metadata.page_count,
        chunks_created=metadata.chunk_count,
        processing_time_ms=metadata.processing_time_ms,
    )


@router.get("/documents")
async def list_documents(request: Request):
    """List all uploaded documents with their metadata."""
    doc_service = request.app.state.doc_service
    documents = doc_service.list_documents()

    return {
        "documents": documents,
        "total": len(documents),
    }


@router.get("/documents/{document_id}")
async def get_document(request: Request, document_id: str):
    """Get details for a specific document."""
    doc_service = request.app.state.doc_service
    metadata = doc_service.get_document(document_id)

    if not metadata:
        raise HTTPException(status_code=404, detail="Document not found")

    return {
        "document_id": metadata.document_id,
        "filename": metadata.filename,
        "page_count": metadata.page_count,
        "chunk_count": metadata.chunk_count,
        "total_characters": metadata.total_characters,
        "processing_time_ms": metadata.processing_time_ms,
    }


@router.delete("/documents/{document_id}")
async def delete_document(request: Request, document_id: str):
    """
    Delete a document and all its chunks from the vector store.
    After deletion, you can no longer chat with this document.
    """
    doc_service = request.app.state.doc_service
    deleted = await doc_service.delete_document(document_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")

    return {"deleted": True, "document_id": document_id}
