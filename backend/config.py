"""
Application configuration using pydantic-settings.

All settings are loaded from environment variables (or .env file).
If a required variable is missing, the app fails at STARTUP — not at 2am
when a user hits that code path.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration for the entire application.
    Every field maps to an environment variable (case-insensitive).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignore extra env vars that don't map to fields
    )

    # ─── App ────────────────────────────────────────────────────────────
    app_name: str = "DocMind"
    app_version: str = "0.1.0"
    debug: bool = False

    # ─── LLM Models ────────────────────────────────────────────────────
    # Primary model: fast + cheap (handles most requests)
    primary_model: str = "llama-3.3-70b-versatile"
    # Fallback model: more capable (used when primary fails)
    fallback_model: str = "llama-3.1-8b-instant"
    # Provider: "groq" or "google"
    llm_provider: str = "groq"
    # Temperature for generation (0 = deterministic, 1 = creative)
    temperature: float = 0.1
    # Max retries before switching to fallback
    max_retries: int = 2

    # ─── API Keys ──────────────────────────────────────────────────────
    google_api_key: str  # Required — used for embeddings
    groq_api_key: str = ""  # Required if llm_provider is "groq"

    # ─── Embeddings ────────────────────────────────────────────────────
    embedding_model: str = "models/gemini-embedding-001"

    # ─── Vector Database (Supabase / PGVector) ─────────────────────────
    database_url: str = "postgresql://postgres:postgres@localhost:5432/docmind"

    # ─── Rate Limiting ─────────────────────────────────────────────────
    rate_limit: str = "20/minute"
    rate_limit_storage: str = "memory"  # "memory" for dev, "redis" for prod

    # ─── Caching ───────────────────────────────────────────────────────
    cache_ttl: int = 3600  # seconds (1 hour)
    cache_max_size: int = 1000  # max entries in cache

    # ─── Security ──────────────────────────────────────────────────────
    max_input_length: int = 10000  # characters
    injection_threshold: float = 0.7  # 0-1, higher = stricter

    # ─── Observability (LangSmith) ─────────────────────────────────────
    langsmith_tracing: bool = True
    langsmith_api_key: str = ""
    langsmith_project: str = "docmind"

    # ─── CORS ──────────────────────────────────────────────────────────
    allowed_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]


# Singleton instance — import this everywhere
settings = Settings()
