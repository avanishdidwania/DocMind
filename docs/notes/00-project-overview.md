# DocMind - Project Overview & Learning Notes

## What We're Building

**DocMind** — An AI-powered Document Intelligence Platform that lets users upload PDFs, extract content (text, tables, images), and chat with their documents using natural language.

## Why This Project

- Combines everything learned from the freeCodeCamp "Production RAG with LangChain & Vector Databases" course
- Modeled after Akshat Jiwrajka's Doc-Analyzer (ranked #1 from IIT project analysis) but with better engineering
- Covers the full production stack: API, agent, retrieval, security, observability

## Architecture Decisions (and Why)

### Tech Stack

| Component | Our Choice | Akshat's Choice | Why Ours is Better |
|-----------|-----------|-----------------|-------------------|
| Vector DB | PGVector (Supabase) | MongoDB + manual cosine | PGVector does similarity search at DB level with HNSW indexes. O(log n) vs O(n). Scales. |
| Agent Framework | LangGraph | Raw if/else routing | State machine with conditional edges. Extensible, debuggable, production-correct. |
| API Framework | FastAPI | FastAPI | Same — it's the right choice for Python APIs |
| LLM | Gemini | Gemini | Same — good balance of quality/cost |
| Security | Rate limiting + injection detection + PII masking | None | Production systems need this. Period. |
| Observability | LangSmith | Disabled | Can't debug what you can't see |
| Embeddings | Google gemini-embedding-001 | sentence-transformers (all-MiniLM-L6-v2) | Higher quality embeddings, simpler setup |

### Production API Request Flow

```
Client Request
    |
    v
[Rate Limiter] ---------> slowapi, tracks requests per IP address
    |
    v
[Security Pipeline] ----> InputSanitizer + PII Detector/Masker + Injection Detector
    |
    v
[Cache Layer] ----------> SHA256 hash key + TTL. Hit? Return cached. Miss? Continue.
    |                     (In-memory for demo. Redis in production.)
    v
[LangGraph Agent] ------> The brain. Primary model → retry → fallback → graceful error.
    |                     User NEVER sees a stack trace.
    v
[Output Validator] -----> Validates response structure (Pydantic)
    |
    v
[Cache Store] ----------> Save response for future identical queries
    |
    v
[Metrics + Logging] ----> Structured JSON logger + MetricsCollector
    |                     (ELK/Datadog/CloudWatch for logs. Prometheus for metrics.)
    v
JSON Response
```

## What I Already Know (from langc-course)

- LLM setup (Gemini, Groq) with LangChain
- Embeddings (Google gemini-embedding-001), cosine similarity, caching
- Document loaders (Text, PDF, Web)
- Text splitters (Recursive, Semantic chunking)
- Basic RAG pipeline with LCEL chains
- Advanced retrieval: Multi-Query, Contextual Compression, Parent Document Retriever
- Hybrid search (BM25 + Vector with custom RRF)
- Production RAG with PGVector/Supabase
- LangSmith observability basics

## What I'm Learning New

1. **FastAPI** — Building production APIs with lifespan, middleware, dependency injection, async handlers
2. **LangGraph** — Stateful agents with built-in safety nets (retry → fallback → graceful error)
3. **Security Layer** — InputSanitizer + PII Detector/Masker + Injection Detector → SecurityPipeline
4. **Caching** — TTL-based with SHA256 keys (in-memory for demo, Redis for production)
5. **Structured Logging** — JSON logger (not print!), needed for ELK/Datadog/CloudWatch
6. **Metrics Collection** — MetricsCollector (dictionary demo) → Prometheus in production
7. **Docker** — Layer caching (deps before code), non-root user, health checks
8. **Deployment** — render.yaml, containerized deployment, Docker as runtime
9. **Production Scaling** — Redis (not in-memory), Prometheus (not dict counters), load balancer in front

## Comparison with Akshat's Doc-Analyzer

### Where His is Stronger
- Full Next.js frontend with virtualized tables, document preview, multi-tab chat
- Image analysis (multimodal — sends page images to Gemini Vision)
- Table modification ("change CGPA for 2027 to 10" → rewrites table with download)
- Deployed and usable (Vercel + cloud MongoDB)

### Where Ours is Stronger (Architecture)
- LangGraph agent vs raw if/else (extensible, debuggable)
- PGVector with HNSW indexes vs in-memory cosine loop (scalable)
- Full security layer (rate limiting, injection detection, PII masking)
- LangSmith observability from day one
- Clean separation of concerns (not a 1000-line god-class)
- Caching layer (reduces costs, improves latency)
- Output validation with fallback models

## Project Structure (Planned)

```
docmind/
├── backend/
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # Environment & settings
│   ├── middleware/
│   │   ├── rate_limiter.py     # slowapi rate limiting
│   │   ├── security.py         # Injection detection + PII masking
│   │   └── cache.py            # Semantic caching layer
│   ├── api/
│   │   ├── routes/
│   │   │   ├── documents.py    # Upload, process, list documents
│   │   │   ├── chat.py         # Chat endpoints
│   │   │   └── health.py       # Health check
│   │   └── dependencies.py     # Shared dependencies
│   ├── services/
│   │   ├── document_service.py # PDF processing pipeline
│   │   ├── retrieval_service.py# Vector search + hybrid retrieval
│   │   └── chat_service.py     # Chat session management
│   ├── agent/
│   │   └── graph.py            # LangGraph agent definition
│   ├── models/
│   │   └── schemas.py          # Pydantic models
│   └── db/
│       └── supabase.py         # PGVector connection
├── docs/
│   └── notes/                  # Learning notes (this folder)
├── .env.example
├── requirements.txt
└── pyproject.toml
```

## Learning Workflow

```
Watch course section → Understand concept → Build it here → Document in notes
```

Each notes file follows this structure:
- What it is (explain to an interviewer)
- Why it matters (production reasoning)
- How we implemented it (code references)
- Interview-ready Q&A
