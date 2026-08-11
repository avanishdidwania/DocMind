"""
Response Cache — SHA256 key + TTL expiration.

Purpose: If someone asked the same question before, return the cached
answer instantly without calling the LLM. Saves cost AND latency.

Current implementation: In-memory dictionary (suitable for single-instance dev).
Production swap: Replace with Redis (shared across instances, survives restarts).

The interface stays the same — only the storage backend changes.
"""

import hashlib
import time
import logging
from dataclasses import dataclass, field
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """A single cached response with metadata."""
    response: str
    model_used: str
    created_at: float  # time.time()
    access_count: int = 0


class ResponseCache:
    """
    LLM response cache with SHA256 keys and TTL-based expiration.

    Key design decisions:
    - SHA256 hash for cache keys (deterministic, fixed-length, collision-resistant)
    - TTL expiration (knowledge changes — stale answers become wrong answers)
    - Max size limit with LRU-style eviction (memory isn't infinite)
    - Thread-safe (FastAPI handles concurrent requests)
    """

    def __init__(self, ttl: int = 3600, max_size: int = 1000):
        """
        Args:
            ttl: Time-to-live in seconds. Entries expire after this duration.
            max_size: Maximum cache entries. Oldest evicted when full.
        """
        self.ttl = ttl
        self.max_size = max_size
        self._cache: dict[str, CacheEntry] = {}
        self._lock = Lock()

        # Metrics
        self.hit_count = 0
        self.miss_count = 0

    def _make_key(self, query: str) -> str:
        """
        SHA256 hash of the query as cache key.

        Why SHA256:
        - Deterministic (same input → same key, always)
        - Fixed 64-char hex string (regardless of query length)
        - Collision-resistant (two different queries won't share a key)
        - Fast computation (negligible overhead)
        """
        return hashlib.sha256(query.strip().lower().encode()).hexdigest()

    def get(self, query: str) -> CacheEntry | None:
        """
        Look up a cached response.

        Returns CacheEntry on hit, None on miss or expired entry.
        """
        key = self._make_key(query)

        with self._lock:
            if key not in self._cache:
                self.miss_count += 1
                return None

            entry = self._cache[key]

            # Check TTL expiration
            if time.time() - entry.created_at > self.ttl:
                # Expired — remove and count as miss
                del self._cache[key]
                self.miss_count += 1
                logger.debug("Cache expired", extra={"key": key[:12]})
                return None

            # Cache HIT
            entry.access_count += 1
            self.hit_count += 1
            logger.debug(
                "Cache hit",
                extra={"key": key[:12], "age_seconds": int(time.time() - entry.created_at)},
            )
            return entry

    def set(self, query: str, response: str, model_used: str) -> None:
        """
        Store a response in the cache.

        If cache is full, evicts the oldest entry (simple FIFO).
        Production upgrade: LRU eviction or Redis with built-in TTL.
        """
        key = self._make_key(query)

        with self._lock:
            # Evict oldest if at capacity
            if len(self._cache) >= self.max_size and key not in self._cache:
                self._evict_oldest()

            self._cache[key] = CacheEntry(
                response=response,
                model_used=model_used,
                created_at=time.time(),
            )

        logger.debug("Cache stored", extra={"key": key[:12], "model": model_used})

    def _evict_oldest(self) -> None:
        """Remove the oldest entry (by creation time)."""
        if not self._cache:
            return

        oldest_key = min(self._cache, key=lambda k: self._cache[k].created_at)
        del self._cache[oldest_key]
        logger.debug("Cache evicted", extra={"key": oldest_key[:12]})

    def invalidate(self, query: str) -> bool:
        """
        Remove a specific entry from cache.
        Useful when underlying data changes (e.g., document re-indexed).
        """
        key = self._make_key(query)
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> int:
        """Clear all cache entries. Returns count of cleared entries."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info("Cache cleared", extra={"entries_cleared": count})
            return count

    def stats(self) -> dict:
        """
        Cache statistics for the /cache/stats endpoint.
        """
        with self._lock:
            total_requests = self.hit_count + self.miss_count
            return {
                "entries": len(self._cache),
                "hit_count": self.hit_count,
                "miss_count": self.miss_count,
                "hit_rate": (
                    self.hit_count / total_requests if total_requests > 0 else 0.0
                ),
                "size_bytes": sum(
                    len(entry.response.encode()) for entry in self._cache.values()
                ),
                "ttl_seconds": self.ttl,
                "max_size": self.max_size,
            }
