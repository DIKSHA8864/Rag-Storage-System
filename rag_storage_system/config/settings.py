"""
Central app configuration, read from environment variables / .env
(see .env.example for the full list). Every field has a default, so
the app boots without any local setup, but every hardcoded path,
limit, or secret that used to live scattered across modules
(storage paths, max upload size, allowed extensions, the admin API
key, the audit log path) now lives here instead - swapping storage
backends or tightening a limit later is an environment-variable
change, not a code change.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Secure RAG Storage System"
    environment: str = "development"

    # ------------------------------------------------------------------
    # Storage paths - each pipeline phase's input/output folder.
    # ------------------------------------------------------------------
    original_storage_path: str = "storage/originals"
    processed_storage_path: str = "storage/processed"
    metadata_storage_path: str = "storage/metadata"
    quarantine_storage_path: str = "storage/quarantine"
    segments_storage_path: str = "storage/segments"
    chunks_storage_path: str = "storage/chunks"
    embeddings_storage_path: str = "storage/embeddings"

    vector_db_path: str = "vector_db/chroma"
    database_path: str = "database/metadata.db"

    # ------------------------------------------------------------------
    # Metadata database backend - "postgres" (production/default) or
    # "sqlite" (fast, zero-setup, used by the test suite). See
    # app/metadata/base.py, sqlite_repository.py, postgres_repository.py.
    # ------------------------------------------------------------------
    metadata_backend: str = "postgres"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "rag_storage"
    postgres_user: str = "raguser"
    postgres_password: str = "ragpassword"

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # "sentence_transformers" (default, free, local, no API key) is the
    # only provider implemented today - see app/embeddings/base.py for
    # the interface a hosted provider would implement instead.
    embedding_provider: str = "sentence_transformers"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # ------------------------------------------------------------------
    # Redis - message broker for the background processing queue (see
    # app/jobs/). POST /process enqueues a job here instead of running
    # extraction/segmentation/chunking/embeddings inline, so a slow
    # document never blocks the API. Point this at a local Redis
    # (docker-compose.yml runs one) or a free tier like Upstash.
    # ------------------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    processing_queue_name: str = "processing"

    # ------------------------------------------------------------------
    # Upload validation
    # ------------------------------------------------------------------
    allowed_extensions: str = ".pdf,.docx,.txt"
    max_file_size_mb: int = 100

    @property
    def allowed_extensions_set(self) -> set[str]:
        return {
            ext.strip().lower()
            for ext in self.allowed_extensions.split(",")
            if ext.strip()
        }

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    # ------------------------------------------------------------------
    # Admin authentication - a single shared API key checked on every
    # data endpoint (see app/security/auth.py). Not per-user accounts
    # or RBAC - just enough to stop the admin API being reachable by
    # anyone who can hit the port. Change this via .env for anything
    # beyond a local demo.
    # ------------------------------------------------------------------
    jwt_secret_key: str = "Diksha@321#"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # ------------------------------------------------------------------
    # End User authentication - a SEPARATE shared key from admin_api_key
    # above, checked via a different header (X-End-User-Key, not
    # X-API-Key - see app/security/auth.py). End Users only ever reach
    # app/api/end_user_api.py's routes (query/compare) - this key grants
    # no access whatsoever to the Owner/Admin API (categories, documents,
    # process, search), which is exactly the point: an End User must
    # never get access to the full document repository.
    # ------------------------------------------------------------------
    end_user_api_key: str = "dev-enduser-key-change-me"

    # ------------------------------------------------------------------
    # End User document comparison (app/analysis/) - matching an End
    # User's submitted text/document against the knowledge base.
    #
    # Score thresholds classify each of the End User's chunks by its
    # single best knowledge-base match (final_score from
    # app/retrieval/reranker.py, 0-1 - a weighted blend of cosine
    # similarity and keyword match, NOT rescaled per-query, so it's
    # comparable across different submissions - see that module's
    # docstring):
    #   >= match       -> "match"          (strong support in the KB)
    #   >= partial      -> "partial_match" (some support, not a full match)
    #   otherwise       -> "gap"           (no adequate support found)
    #
    # Calibrated empirically (all-MiniLM-L6-v2, this project's default
    # embedding model - see EMBEDDING_MODEL) against a real knowledge
    # base: near-duplicate wording of an indexed chunk scored ~0.55,
    # the same topic in clearly different wording ~0.36, and an
    # unrelated sentence ~0.01. Re-tune these if you switch embedding
    # models - the raw cosine-similarity range a model produces isn't
    # standardized across models.
    #
    # overall_match_score (0-100) is a weighted combination of how much
    # of the submission is covered (matched/partially matched, not a
    # gap) and how confident those matches are on average - see
    # app/analysis/matcher.py. Both scoring and thresholds are
    # deliberately config, not something an LLM decides per request.
    # ------------------------------------------------------------------
    match_score_threshold_match: float = 0.5
    match_score_threshold_partial: float = 0.3
    match_score_coverage_weight: float = 0.6
    match_score_confidence_weight: float = 0.4

    # "template" (default, free, deterministic, no API key needed) is
    # the only narrative provider that requires nothing further to run
    # - see app/analysis/base.py for the interface a hosted LLM
    # provider implements instead, and app/analysis/claude_provider.py
    # for the one implemented today (set NARRATIVE_PROVIDER=claude and
    # ANTHROPIC_API_KEY to use it). Only prose (executive summary,
    # per-item narrative, recommendations) ever goes through this -
    # overall_match_score above never does.
    narrative_provider: str = "template"
    anthropic_api_key: str = ""
    analysis_model: str = "claude-opus-5"

    # ------------------------------------------------------------------
    # Audit log - one JSON line per upload/replace/delete/rename, see
    # app/security/audit_log.py.
    # ------------------------------------------------------------------
    audit_log_path: str = "logs/audit.log"

    def resolve(self, relative_path: str) -> Path:
        """Resolve a configured path relative to the project root."""

        path = Path(relative_path)
        return path if path.is_absolute() else PROJECT_ROOT / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
