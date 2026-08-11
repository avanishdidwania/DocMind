# DocMind

Production-grade RAG (Retrieval-Augmented Generation) system for document intelligence. Upload PDFs, ask questions, get grounded answers with source citations.

Built with a production-first architecture: security pipeline, hybrid retrieval, LangGraph agent with failover, structured observability, and Docker deployment.

## Architecture

```
Client Request
    │
    ▼
┌─────────────────┐
│   Rate Limiter   │  slowapi — 20 req/min per IP
└────────┬────────┘
         ▼
┌─────────────────┐
│ Security Pipeline│  InputSanitizer → InjectionDetector → PIIMasker
└────────┬────────┘
         ▼
┌─────────────────┐
│   Cache Layer    │  SHA256 + TTL (Redis in prod)
└────────┬────────┘
         ▼
┌─────────────────┐
│ Hybrid Retrieval │  BM25 (keyword) + Vector (semantic) + RRF scoring
└────────┬────────┘
         ▼
┌─────────────────┐
│ LangGraph Agent  │  Primary → Retry → Fallback → Graceful Error
└────────┬────────┘
         ▼
┌─────────────────┐
│ Metrics + Logs   │  Structured JSON logging + MetricsCollector
└────────┬────────┘
         ▼
    JSON Response
```

## Features

- **Hybrid Retrieval** — BM25 keyword search + vector semantic search, combined with Reciprocal Rank Fusion (RRF). Handles both exact-term queries and conceptual questions.
- **LangGraph Agent** — Stateful agent with built-in safety net. Primary model → retry → fallback model → graceful error. Users never see a stack trace.
- **Security Pipeline** — Three-stage pipeline: input sanitization, prompt injection detection (18 patterns), PII masking (credit cards, SSN, email, phone, Aadhaar, PAN).
- **Conversation Memory** — Stateful chat sessions with configurable history window. Follow-up questions work naturally.
- **Production Observability** — Structured JSON logging for ELK/Datadog/CloudWatch. MetricsCollector tracking latency, errors, cache rates, token usage.
- **Auto-selecting Vector Store** — Detects PostgreSQL URL → PGVector. Otherwise → Chroma. Zero config change needed.
- **Response Caching** — SHA256 key + TTL expiration. Skips cache for conversations with history (context-dependent answers).
- **Docker Ready** — Dockerfile with layer caching, non-root user, health check. docker-compose with optional PGVector.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI, uvicorn, slowapi |
| Agent | LangGraph, LangChain |
| LLM | Google Gemini (configurable primary + fallback) |
| Embeddings | Google gemini-embedding-001 |
| Vector DB | PGVector (prod) / Chroma (dev) |
| Retrieval | Hybrid — BM25 + Vector + RRF |
| Security | Custom pipeline (sanitizer + injection + PII) |
| Config | pydantic-settings |
| Observability | Structured JSON logging, LangSmith |
| Deployment | Docker, Render |

## Quick Start

```bash
# Clone
git clone https://github.com/avanishdidwania/DocMind.git
cd DocMind

# Setup (using uv — fast)
uv venv && uv pip install -r requirements.txt

# Configure
cp backend/.env.example backend/.env
# Add your GOOGLE_API_KEY to backend/.env

# Run
cd backend
uvicorn main:app --reload

# Open API docs
# http://localhost:8000/docs
```

## Docker

```bash
# Build and run
docker compose up

# With PostgreSQL/PGVector
docker compose --profile db up
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/chat` | Chat with documents or general Q&A |
| POST | `/api/documents/upload` | Upload a PDF for processing |
| GET | `/api/documents` | List uploaded documents |
| DELETE | `/api/documents/{id}` | Delete a document |
| GET | `/api/health` | Health check (component status) |
| GET | `/api/metrics` | System metrics |
| GET | `/api/cache/stats` | Cache performance stats |
| GET | `/api/chat/sessions` | List chat sessions |

## Project Structure

```
backend/
├── main.py                      # FastAPI app + lifespan
├── config.py                    # pydantic-settings
├── agent/graph.py               # LangGraph agent (safety net)
├── middleware/
│   ├── security.py              # SecurityPipeline
│   ├── cache.py                 # Response cache
│   └── monitoring.py            # JSON logger + metrics
├── api/routes/
│   ├── chat.py                  # Chat endpoint (full pipeline)
│   ├── documents.py             # Document CRUD
│   └── health.py                # System endpoints
├── services/
│   ├── document_service.py      # PDF processing pipeline
│   ├── retrieval_service.py     # Hybrid retrieval (BM25+Vector+RRF)
│   └── memory_service.py        # Conversation sessions
├── db/vector_store.py           # Auto-selecting vector backend
└── models/schemas.py            # Pydantic models
```

## Design Decisions

**Why LangGraph over raw chains?**
Error handling is architectural, not bolted-on. The safety net (retry → fallback → graceful error) is part of the graph, making the system extensible and debuggable via LangSmith.

**Why hybrid retrieval?**
Vector search fails on exact terms ("error code E_TIMEOUT"). BM25 fails on semantic queries ("how does authentication work?"). RRF combines both without score normalization.

**Why PGVector over Chroma in production?**
HNSW indexes give O(log n) search. Persistent across restarts. Shared across horizontally-scaled instances. Managed by Supabase with backups.

**Why a security pipeline?**
LLM APIs without injection detection are exploitable. PII masking is a compliance requirement (GDPR). Rate limiting prevents cost abuse. Most RAG tutorials skip all of this.

## Environment Variables

```env
GOOGLE_API_KEY=your-key          # Required
PRIMARY_MODEL=gemini-flash-latest
FALLBACK_MODEL=gemini-flash-latest
DATABASE_URL=postgresql://...    # Supabase PGVector (optional)
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=your-key
RATE_LIMIT=20/minute
CACHE_TTL=3600
```

## License

MIT
