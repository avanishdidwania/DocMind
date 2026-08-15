# 07 - Streaming, Multi-Doc Chat, Contextual Compression, Evaluation

## Streaming Responses (Server-Sent Events)

### What It Is

Instead of the user waiting 3-5 seconds staring at a blank screen, tokens appear as they're generated — word by word. This is how ChatGPT, Claude, and every modern AI product works.

### How It Works

**Protocol: Server-Sent Events (SSE)**

```
Client sends: POST /api/chat/stream {message: "..."}
Server responds: Content-Type: text/event-stream

data: {"token": "Retrieval", "done": false}
data: {"token": "-Augmented", "done": false}
data: {"token": " Generation", "done": false}
...
data: {"token": "", "done": true, "metadata": {"model": "...", "latency_ms": 3500}}
```

**Key implementation details:**
- FastAPI `StreamingResponse` with `media_type="text/event-stream"`
- LangChain's `llm.astream(messages)` yields chunks as generated
- `async for chunk in llm.astream(...)` — each chunk is one or a few tokens
- Final event has `done: true` + metadata (model used, latency, sources)

**Why SSE over WebSockets:**
- Simpler (HTTP, not a persistent connection)
- Works through load balancers and CDNs without special config
- Client can use `fetch()` + `ReadableStream` or `EventSource`
- Good enough for one-direction streaming (server → client)

### Interview Answer

"We use Server-Sent Events for streaming because it's simpler than WebSockets for our use case (unidirectional server-to-client). The endpoint uses FastAPI's StreamingResponse with LangChain's async streaming API. Each token is sent as a JSON event, and the final event includes metadata. This reduces perceived latency from 3-5 seconds to near-instant — users see the first token within 200ms."

---

## Multi-Document Chat

### What It Is

Query across multiple uploaded documents in one request. Instead of "ask about document A" or "ask about document B," you can say "Compare what document A says about X vs document B."

### How It Works

```python
# Request
POST /api/chat
{
    "message": "Compare the security approaches in both documents",
    "document_ids": ["doc_abc", "doc_xyz"]
}
```

**Implementation:**
- `retrieve_multi()` searches each document independently (both vector + BM25)
- All results are pooled together
- RRF combines them into a single ranked list
- Chunks from different documents appear in the same context, with source attribution

**Why this matters:**
- Real users have multiple documents
- "Compare contract A vs contract B" is a common need
- Single-doc retrieval is limiting

### Interview Answer

"Our multi-document chat uses the same hybrid retrieval (BM25 + Vector + RRF) but runs it across multiple documents in parallel. Results from each document are pooled and re-ranked with RRF, so the most relevant chunks from ANY document float to the top. Each chunk carries its source metadata, so the LLM can cite which document its answer comes from."

---

## Contextual Compression

### What It Is

After retrieval, use a lightweight LLM call to extract ONLY the sentences that are relevant to the question from each chunk. Throw away the noise.

### The Problem It Solves

Retrieved chunks are ~1000 characters each. Maybe only 2 sentences in a chunk actually answer the question. The rest is background, unrelated details, or filler. Sending all of it to the LLM:
- Wastes tokens (costs money)
- Adds noise (can confuse the model)
- Takes context window space (fewer chunks can fit)

### How It Works

```
Before compression:
  Chunk: "DocMind was founded in 2026. It uses FastAPI for the web layer.
           The team consists of 3 engineers. LangGraph handles agent
           orchestration with retry and fallback. Office is in India."

Question: "What framework handles the agent?"

After compression:
  "LangGraph handles agent orchestration with retry and fallback."
```

**Implementation:**
- One LLM call per chunk with a focused prompt: "Extract ONLY sentences relevant to the question"
- If nothing is relevant → chunk is filtered out entirely
- Falls back to original chunk on failure (graceful degradation)
- Logged: compression ratio (e.g., "compressed to 35% of original")

### Trade-offs

| Pro | Con |
|-----|-----|
| Cleaner context → better answers | Extra LLM call per chunk (latency + cost) |
| Fewer tokens in final prompt → cheaper | If compression is too aggressive, loses info |
| More room for additional chunks | Adds ~500ms per chunk |

### Interview Answer

"After hybrid retrieval returns chunks, we run contextual compression — a lightweight LLM call on each chunk that extracts only the sentences relevant to the query. This typically compresses to 30-40% of original size, meaning less noise in the final prompt, lower token costs, and better answer quality. It's an extra LLM call per chunk, but we use a fast model with a simple extraction prompt, so the latency trade-off is worth it."

---

## Evaluation Pipeline

### What It Is

Automated testing of RAG quality. Most people build a RAG system and never measure if it's actually working well. This answers: "Is my retrieval finding the right chunks? Are the answers grounded in context?"

### Two Scores

1. **Retrieval Relevance (1-5)** — Did we find the RIGHT chunks?
   - 5 = Context contains everything needed to answer
   - 1 = Context is completely irrelevant

2. **Answer Faithfulness (1-5)** — Is the answer GROUNDED in context?
   - 5 = Every claim in the answer is supported by the context
   - 1 = Answer is completely hallucinated

### How It Works

```
POST /api/evaluate/{document_id}?n_questions=5

Pipeline:
1. Generate synthetic Q&A pairs from the document (LLM creates questions + expected answers)
2. For each question:
   a. Run through retrieval pipeline → get context
   b. Score retrieval relevance (LLM-as-judge)
   c. Run through agent → get answer
   d. Score answer faithfulness (LLM-as-judge)
3. Return aggregate scores + per-question breakdown
```

**Response format:**
```json
{
  "scores": {
    "retrieval_relevance": {"average": 4.2, "interpretation": "Good"},
    "answer_faithfulness": {"average": 4.6, "interpretation": "Excellent"}
  },
  "results": [
    {"question": "...", "actual_answer": "...", "retrieval_relevance": 5, "answer_faithfulness": 4},
    ...
  ]
}
```

### When to Use

- After uploading a new document → verify it works
- After changing chunk size or overlap → compare quality
- After changing retrieval K or weights → measure impact
- As a regression test → "did my changes make things worse?"

### LLM-as-Judge Pattern

Using an LLM to evaluate another LLM's output. Key principle: the judge prompt must be simple and specific:

```
"Rate 1-5 how relevant this context is for answering this question.
1 = Completely irrelevant, 5 = Perfectly relevant.
Respond with ONLY a number."
```

Simple prompts → consistent scores → reliable evaluation.

### Interview Answer

"We have an automated evaluation pipeline that measures RAG quality on two axes: retrieval relevance and answer faithfulness. It generates synthetic Q&A pairs from the document, runs each through the full pipeline, and uses LLM-as-judge to score results on a 1-5 scale. This lets us quantify the impact of parameter changes (chunk size, retrieval K, compression) and catch regressions. Most RAG systems have no quality measurement — ours can tell you it's 4.2/5 on relevance and 4.6/5 on faithfulness."

---

## Key Interview Questions

**Q: How do you handle streaming in a RAG pipeline?**
A: Server-Sent Events via FastAPI StreamingResponse. The security and retrieval pipeline runs synchronously (they're fast), then we stream the LLM generation via `astream()`. Each token is a JSON event. The final event includes metadata. This gives near-instant first-token latency while maintaining the full production pipeline.

**Q: How does multi-document retrieval work?**
A: We run hybrid retrieval (BM25 + Vector) independently on each document, pool all results, then apply RRF to produce a single ranked list. Chunks carry source metadata so the LLM knows which document each fact came from. This enables cross-document comparison queries.

**Q: What's contextual compression and when would you use it?**
A: It's a post-retrieval step that uses a fast LLM to extract only the query-relevant sentences from each chunk. Use it when: chunks are large, context window is limited, or answer quality suffers from noise. The trade-off is one extra LLM call per chunk (~500ms), which is worth it for precision-critical use cases.

**Q: How do you measure RAG quality?**
A: Two automated metrics: retrieval relevance (1-5, did we find the right chunks) and answer faithfulness (1-5, is the answer grounded in context). We generate synthetic questions from the document, run them through the pipeline, and score with LLM-as-judge. This quantifies the impact of any system change and catches regressions.

**Q: What's the difference between faithfulness and relevance?**
A: Relevance measures the RETRIEVAL stage — did we find the right information? Faithfulness measures the GENERATION stage — given the context, did the LLM stay grounded or hallucinate? You can have high relevance (found great chunks) but low faithfulness (LLM ignored them and made stuff up), or vice versa. You need both to be high.


---

## Self-Correcting RAG (Agentic Retrieval)

### What It Is

The retrieval system grades its own quality and retries with a reformulated query if the initial chunks aren't relevant enough. Instead of blindly passing whatever chunks the vector store returns, an LLM decides: "Is this actually useful for answering the question?"

This is the "agentic" part of Agentic RAG — the system has agency to fix its own mistakes.

### The Problem It Solves

Normal RAG fails silently. If you ask "What's the uptime target?" but the chunks returned are about caching and latency (because "uptime" isn't a literal keyword in the document), regular RAG generates a bad answer from irrelevant context — or worse, hallucinates.

Self-correcting RAG catches this: "These chunks don't answer the question. Let me rephrase and try again."

### The Flow

```
User Query: "What's the uptime target?"
    │
    ▼
[Hybrid Retrieval] → finds chunks about caching/latency (not uptime)
    │
    ▼
[Grade] → LLM: "Do these chunks answer 'uptime target'?" → NO
    │
    ▼
[Reformulate] → LLM: "Rephrase for better retrieval" → "system reliability availability SLA percentage"
    │
    ▼
[Hybrid Retrieval] → finds "99.9% via LangGraph safety net"
    │
    ▼
[Grade] → YES → proceed to generation
    │
    ▼
[Agent] → "The uptime target is 99.9%"
```

### Implementation

Three new methods in `RetrievalService`:

```python
async def retrieve_with_correction(self, query, document_id):
    """Main entry point. Loops: retrieve → grade → reformulate → retry (max 2)."""

async def _grade_retrieval(self, query, context) -> bool:
    """LLM-as-judge: 'Does this context answer the question? YES/NO'"""

async def _reformulate_query(self, original_query, last_query) -> str:
    """LLM rephrases query: different keywords, synonyms, more specific/general"""
```

Key design decisions:
- **Max 2 attempts** — prevents infinite loops and runaway API costs
- **Graceful fallback** — if grading or reformulation fails, return whatever we have (don't crash)
- **Grade prompt is simple** — "YES or NO" gives consistent, parseable responses
- **Reformulation prompt gives strategies** — "try synonyms, be more specific, break into phrases"

### Cost Analysis

| Scenario | LLM Calls | Latency Added |
|----------|-----------|---------------|
| Good retrieval (pass first grade) | +1 (grading) | +0.5-1s |
| Poor retrieval (reformulate once) | +3 (grade + reformulate + grade) | +1.5-3s |
| Very poor (max attempts) | +4 | +2-4s |

Most queries (~80%) pass on first attempt. The extra 0.5-1s for grading is worth it for the 20% of queries that would have failed silently.

### Interview Answer

"Our retrieval is self-correcting. After hybrid search returns chunks, an LLM grades them: 'Does this context answer the question?' If NO, it reformulates the query using different keywords or phrasing and retrieves again — up to 2 attempts. This catches cases where the initial retrieval misses due to vocabulary mismatch. Most queries pass on first attempt (~0.5s overhead), but for the 20% that would have failed, this is the difference between a correct answer and a hallucination."

### Key Interview Questions

**Q: What's the difference between self-correcting and regular RAG?**
A: Regular RAG retrieves once and generates from whatever it gets — if retrieval is bad, the answer is bad. Self-correcting RAG adds a feedback loop: grade retrieval quality, reformulate if poor, retry. It catches vocabulary mismatch and retrieval failures that regular RAG passes through silently.

**Q: Why not just retrieve more chunks (higher K)?**
A: Higher K adds noise. You get more chunks but they're less relevant on average. Self-correcting is targeted — it only retries when the specific query didn't work, and it reformulates to find what's actually needed. It's precision, not recall.

**Q: How do you prevent infinite loops?**
A: Hard cap at 2 attempts. Also, if reformulation returns the same query (can't think of anything different), we return what we have. Graceful degradation over infinite retrying.

**Q: What's the latency impact?**
A: +0.5-1s for grading on every query (one fast LLM call). Only queries that fail grading pay the reformulation cost (+1-2s more). In practice, ~80% of queries pass on first attempt because hybrid retrieval is already good.

---

## Multi-Provider LLM Architecture

### What It Is

Using different LLM providers for different tasks based on cost/speed/quality tradeoffs:
- **Groq (Llama 3.3 70B)** — for text generation (fast, generous free tier, 30 req/min)
- **Google (gemini-embedding-001)** — for embeddings only (no Groq embedding model exists)

### Why This Pattern

No single provider is best at everything:
- Google Gemini: good quality, but 20 req/day free tier (hit rate limits fast)
- Groq: incredibly fast (500ms vs 3-5s), generous limits, but no embedding models
- OpenAI: high quality, expensive, slow

Production systems mix providers based on task requirements.

### Implementation

```python
def _create_llm(model: str):
    """Factory that creates the right LLM based on configured provider."""
    if settings.llm_provider == "groq":
        return ChatGroq(model=model, api_key=settings.groq_api_key, ...)
    else:
        return ChatGoogleGenerativeAI(model=model, ...)
```

Every component that needs an LLM calls `_create_llm()` — agent, evaluation, self-correction, compression. Swap provider in one place (config), everything switches.

### Interview Answer

"We use a multi-provider architecture: Groq for text generation (10x faster, generous rate limits) and Google for embeddings (Groq doesn't offer embedding models). A factory function `_create_llm()` abstracts the provider — we can switch by changing one config variable. This is a common production pattern: optimize each task for the best cost/speed/quality tradeoff instead of being locked to one provider."

**Q: What happens if Groq goes down?**
A: Our LangGraph safety net handles this. Primary model (Groq Llama 70B) fails → retry → fallback model (Groq Llama 8B, faster/simpler) → graceful error. We could also configure the fallback to a completely different provider (e.g., Google) for provider-level redundancy.
