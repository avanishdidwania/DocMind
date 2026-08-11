# 06 - Caching & Monitoring

## Part 1: Caching

### What It Is

A layer that stores previous LLM responses and returns them instantly for identical (or similar) future queries, without calling the LLM again.

### Why Caching is Critical for LLM APIs

- **Cost:** Each Gemini/GPT call costs tokens. Repeated questions = wasted money.
- **Latency:** LLM calls take 1-5 seconds. Cache hits take <1ms.
- **Rate limits:** LLM providers have rate limits. Caching reduces API calls.
- **User experience:** Instant response vs waiting seconds.

In practice, caching can reduce LLM costs by 30-60% depending on query patterns.

### Implementation (Course Approach)

**Cache key:** SHA256 hash of the query string
**Storage:** In-memory dictionary (demo) → Redis in production
**Expiration:** TTL (Time To Live) — entries expire after a set duration

```python
import hashlib
import time

class ResponseCache:
    def __init__(self, ttl: int = 3600):
        self.cache = {}       # key → (response, timestamp)
        self.ttl = ttl        # seconds until expiry
    
    def _make_key(self, query: str) -> str:
        """SHA256 hash of the query as cache key"""
        return hashlib.sha256(query.encode()).hexdigest()
    
    def get(self, query: str) -> str | None:
        """Lookup. Returns None on miss or expired entry."""
        key = self._make_key(query)
        if key in self.cache:
            response, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return response  # Cache HIT
            else:
                del self.cache[key]  # Expired
        return None  # Cache MISS
    
    def set(self, query: str, response: str):
        """Store a response."""
        key = self._make_key(query)
        self.cache[key] = (response, time.time())
    
    def stats(self) -> dict:
        """Cache statistics for monitoring."""
        return {
            "entries": len(self.cache),
            "size_bytes": sum(len(v[0]) for v in self.cache.values()),
        }
```

### SHA256 — Why This Hash?

- **Deterministic:** Same input always gives same hash
- **Fixed length:** 64-character hex string regardless of input length
- **Collision resistant:** Practically impossible for two different queries to produce the same hash
- **Fast:** Negligible computation time

### TTL — Why Entries Must Expire

- Knowledge bases change (you re-index documents, data updates)
- Stale cached answers become wrong answers
- Memory is finite — old entries should be evicted
- Typical TTL: 1 hour for dynamic content, 24 hours for static knowledge

### Exact Match vs Semantic Caching

| | Exact Match (SHA256) | Semantic Cache |
|--|---------------------|----------------|
| "What is RAG?" == "What is RAG?" | ✓ HIT | ✓ HIT |
| "What is RAG?" == "Explain RAG" | ✗ MISS (different hash) | ✓ HIT (similar embedding) |
| Speed of lookup | O(1) dict lookup | O(n) similarity search or ANN |
| Implementation | Simple | Requires embedding model |
| Hit rate | Lower | Higher |
| Course uses | ✓ This one | |
| Production option | | LangChain SemanticCache, GPTCache |

### In-Memory vs Redis (Production)

**In-memory (course demo):**
- ✓ Simple, zero dependencies
- ✗ Lost on restart
- ✗ Not shared across multiple server instances
- ✗ One server's cache doesn't help another

**Redis (production):**
- ✓ Persists across restarts
- ✓ Shared across all server instances (horizontal scaling)
- ✓ Built-in TTL support (`EXPIRE key 3600`)
- ✓ Memory-efficient data structures
- ✗ Additional infrastructure to manage

**Interview answer:** "We use SHA256-hashed exact match caching with TTL. In our demo it's in-memory, but production would use Redis for three reasons: persistence across deploys, shared state across horizontally-scaled instances, and built-in TTL support. For even higher hit rates, you could upgrade to semantic caching where embeddings determine cache matches."

---

## Part 2: Monitoring

### Structured JSON Logging

**The rule: We NEVER use `print()` in production.**

Why print fails:
```python
print("Error happened")  # What error? When? For which user? What request?
```

Why structured JSON works:
```python
logger.error("LLM call failed", extra={
    "request_id": "abc-123",
    "user_id": "user_456",
    "model": "gemini-2.0-flash",
    "latency_ms": 5200,
    "error_type": "timeout",
    "query_length": 150,
    "timestamp": "2026-08-11T14:30:00Z"
})
```

Output (JSON):
```json
{
    "level": "ERROR",
    "message": "LLM call failed",
    "request_id": "abc-123",
    "user_id": "user_456",
    "model": "gemini-2.0-flash",
    "latency_ms": 5200,
    "error_type": "timeout",
    "query_length": 150,
    "timestamp": "2026-08-11T14:30:00Z"
}
```

**Why JSON format:**
- Log aggregators (ELK Stack, Datadog, CloudWatch) parse JSON automatically
- You can search: "show me all ERROR logs where latency_ms > 3000 in the last hour"
- You can build dashboards: "graph error rate over time, broken down by model"
- You can set alerts: "notify me when error_type=timeout exceeds 5% of requests"

**None of this is possible with `print("Error happened")`.**

### Log Aggregators (Where Logs Go)

| Tool | What It Does |
|------|-------------|
| **ELK Stack** | Elasticsearch (store+search) + Logstash (ingest) + Kibana (visualize) |
| **Datadog** | All-in-one SaaS: logs + metrics + traces + dashboards + alerts |
| **CloudWatch** | AWS native logging + metrics + alerts |

These tools ingest your structured JSON logs and let you:
- Search across millions of log entries
- Build dashboards
- Set up alerts ("page me if error rate > 5%")
- Correlate logs with metrics and traces

### MetricsCollector

**What to track:**
```python
class MetricsCollector:
    def __init__(self):
        self.request_count = 0
        self.error_count = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.total_latency_ms = 0
        self.model_usage = {}  # model_name → count
        self.token_usage = 0
    
    def record_request(self, latency_ms, model, tokens, cached, error=None):
        self.request_count += 1
        self.total_latency_ms += latency_ms
        if cached:
            self.cache_hits += 1
        else:
            self.cache_misses += 1
        if error:
            self.error_count += 1
        self.model_usage[model] = self.model_usage.get(model, 0) + 1
        self.token_usage += tokens
    
    def summary(self) -> dict:
        return {
            "total_requests": self.request_count,
            "error_rate": self.error_count / max(self.request_count, 1),
            "cache_hit_rate": self.cache_hits / max(self.cache_hits + self.cache_misses, 1),
            "avg_latency_ms": self.total_latency_ms / max(self.request_count, 1),
            "total_tokens": self.token_usage,
            "model_usage": self.model_usage,
        }
```

### Dictionary Counters vs Prometheus (Production)

**Course demo:** Dictionary counters (simple, in-memory)
- ✓ Zero dependencies, easy to understand
- ✗ Lost on restart
- ✗ Not queryable from outside the process
- ✗ No time-series data (can't graph "latency over time")

**Production: Prometheus**
- Industry standard for metrics collection
- Exposes a `/metrics` endpoint in a specific format
- Scraped by Prometheus server at regular intervals
- Visualized with Grafana dashboards
- Built-in alerting rules

```python
# Prometheus approach (what production looks like):
from prometheus_client import Counter, Histogram

REQUEST_COUNT = Counter('api_requests_total', 'Total requests', ['endpoint', 'status'])
LATENCY = Histogram('api_latency_seconds', 'Request latency', ['endpoint'])
CACHE_HITS = Counter('cache_hits_total', 'Cache hit count')

# Usage:
REQUEST_COUNT.labels(endpoint='/chat', status='200').inc()
LATENCY.labels(endpoint='/chat').observe(latency_seconds)
```

### Key Metrics to Track for LLM APIs

| Metric | Why |
|--------|-----|
| Request count | Traffic volume, billing |
| Error rate | System health |
| Latency (p50, p95, p99) | User experience |
| Cache hit rate | Cost efficiency |
| Token usage | Cost tracking |
| Model usage breakdown | Which fallbacks are firing |
| Injection attempts | Security monitoring |
| Rate limit triggers | Abuse detection |

## Interview Questions

**Q: Why not just use print statements for logging?**
A: Print gives you unstructured text that's impossible to search, filter, or alert on at scale. Structured JSON logging lets log aggregators (ELK, Datadog, CloudWatch) parse each field — you can query "show me all errors for user X where latency > 3 seconds." In production with millions of requests, this is the difference between finding a bug in minutes vs days.

**Q: How does caching work in your LLM API?**
A: We hash the query with SHA256 to create a cache key, then check if we have a valid (non-expired) response stored. If yes, we return it instantly without calling the LLM. If not, we call the LLM and store the response with a TTL. This reduces both cost (fewer API calls) and latency (milliseconds vs seconds). In production, we'd use Redis instead of in-memory to share cache across instances.

**Q: What's the tradeoff with caching LLM responses?**
A: The main tradeoff is staleness. If your knowledge base changes (new documents indexed), cached answers might be outdated. You manage this with TTL (entries expire after a set time) and cache invalidation (clear relevant entries when data changes). Exact-match caching also misses paraphrased queries — "What is X?" and "Explain X" are different cache keys.

**Q: What metrics do you track and why?**
A: Five key categories: (1) Reliability — error rate, by type. (2) Performance — latency percentiles (p50, p95, p99). (3) Cost — token usage, cache hit rate. (4) Security — injection attempts, rate limit triggers. (5) Usage — request volume, model breakdown. These feed dashboards and alerts so we catch issues before users report them.

**Q: How would you set up alerting for this system?**
A: Prometheus alerting rules or Datadog monitors. Critical alerts: error rate > 5% for 5 minutes, p99 latency > 10 seconds, primary model fallback rate > 20%. Warning alerts: cache hit rate drops below 30%, token usage spikes, unusual rate limit trigger patterns. On-call gets paged for critical, Slack notification for warnings.
