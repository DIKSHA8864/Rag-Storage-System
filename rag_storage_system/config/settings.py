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

    # Vault sync (app/vault_sync/) - mirror a folder that Dropbox / Google
    # Drive's desktop app keeps in sync (VAULT_SYNC_DIR), or a Dropbox folder
    # via the Dropbox API (DROPBOX_* - downloaded into VAULT_MIRROR_DIR first),
    # into VAULT_SYNC_TENANT_ID's library. Both empty = sync is off.
    vault_sync_dir: str = ""
    vault_sync_tenant_id: int = 1
    vault_mirror_dir: str = "storage/vault_mirror"
    vault_sync_interval_seconds: int = 300
    dropbox_app_key: str = ""
    dropbox_app_secret: str = ""
    dropbox_refresh_token: str = ""
    dropbox_root_path: str = ""  # e.g. "/AshiLegal Library"; "" = the whole app folder

    # ------------------------------------------------------------------
    # Guided intake (flow v2)
    # ------------------------------------------------------------------
    # Library folder holding the firm's intake question frameworks - the
    # follow-up questions after a client's story are drawn only from it
    # (app/intake_engine/follow_ups.py). "" = no follow-ups.
    intake_framework_category: str = "Question Frameworks"

    # Analytics cost estimate: '{"<model>": [<input>, <output>]}' = USD per million
    # input / output tokens per model (copy from your Anthropic pricing page).
    # Empty = token counts only; cost is never guessed.
    llm_prices: str = ""

    # "Talk to a person" requests are also emailed here (comma-separated).
    # Empty = they only appear under Admin -> Requests.
    handoff_notify_emails: str = ""

    # ------------------------------------------------------------------
    # Upload validation
    # ------------------------------------------------------------------
    allowed_extensions: str = ".pdf,.docx,.txt"

    # Virus scanning of every upload (app/security/virus_scan.py):
    # "clamav" = scan with a ClamAV daemon, "none" = off. When on and the
    # scanner can't give a verdict, uploads are refused (fails closed).
    virus_scanner: str = "none"
    clamav_host: str = "localhost"
    clamav_port: int = 3310
    clamav_socket: str = ""  # e.g. /var/run/clamav/clamd.ctl - used instead of host/port when set
    clamav_timeout_seconds: float = 60
    max_file_size_mb: int = 100
    cors_allowed_origins: str = "http://localhost:3000"
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
    jwt_secret_key: str = ""
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
    # Blueprint Work Plan "Model usage": the mid-tier model everywhere
    # (answers, relevance check, intake follow-ups, image captions), the
    # top-tier model only where quality measurably requires it - the
    # intake report's reasoning and complaint drafting (DRAFTING_MODEL).
    analysis_model: str = "claude-sonnet-5"
    drafting_model: str = "claude-opus-5-5"

    # ------------------------------------------------------------------
    # Audit log - one JSON line per upload/replace/delete/rename, see
    # app/security/audit_log.py.
    # ------------------------------------------------------------------
    audit_log_path: str = "logs/audit.log"
    sentry_dsn: str = ""
    # ------------------------------------------------------------------
    # Phase 3/5 - Multimodal intake (app/multimodal/) - Voice/Video.
    # OCR/STT/Vision are pluggable, provider-agnostic interfaces
    # (app/multimodal/ocr.py, speech_to_text.py, vision.py) - "mock"
    # (default) needs no external service or API key. It returns a
    # clearly-labeled placeholder instead of fabricating plausible
    # text, so a report built from it can never be mistaken for a real
    # extraction.
    #
    # Real providers (opt in, same swappable-backend principle as
    # EMBEDDING_PROVIDER/NARRATIVE_PROVIDER):
    #   OCR_PROVIDER=tesseract     - local Tesseract OCR, free, no API
    #                                key (needs the `tesseract-ocr`
    #                                system package)
    #   STT_PROVIDER=whisper       - local Whisper (faster-whisper),
    #                                free, no API key, transcribes
    #                                audio AND video files identically
    #                                (see speech_to_text.py's
    #                                WhisperSTTProvider)
    #   VISION_PROVIDER=claude     - Claude's vision input, needs
    #                                ANTHROPIC_API_KEY (already used by
    #                                NARRATIVE_PROVIDER=claude above)
    # ------------------------------------------------------------------
    ocr_provider: str = "mock"
    stt_provider: str = "mock"
    vision_provider: str = "mock"

    # Only read when STT_PROVIDER=whisper - see speech_to_text.py's
    # WhisperSTTProvider. Larger sizes are more accurate and slower;
    # "base" is a reasonable default for CPU-only self-hosting.
    whisper_model_size: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # How many representative frames app/multimodal/video_processor.py
    # samples (evenly spaced across the video's duration, via PyAV - no
    # ffmpeg subprocess needed) and captions through VISION_PROVIDER,
    # in addition to transcribing the video's audio track. 0 disables
    # frame captioning entirely (audio-only, the original behavior) -
    # useful to avoid per-frame cost with a paid Vision provider.
    video_frame_sample_count: int = 3

    # Separate root from ORIGINAL_STORAGE_PATH above - a Client's
    # intake uploads must stay logically separate from the Owner's
    # knowledge base (see app/storage/__init__.py's
    # get_intake_storage_backend()).
    intake_storage_path: str = "storage/intake"
    intake_quarantine_storage_path: str = "storage/intake_quarantine"

    # Wider than ALLOWED_EXTENSIONS above (PDF/DOCX/TXT only) - Client
    # intake also accepts images, audio, video, and a ZIP of any of
    # those (app/multimodal/zip_processor.py).
    intake_allowed_extensions: str = (
        ".pdf,.docx,.txt,.png,.jpg,.jpeg,.tiff,.bmp,"
        ".mp3,.wav,.m4a,.weba,.ogg,.mp4,.mov,.avi,.webm,.zip"
    )
    intake_max_file_size_mb: int = 200
    intake_zip_max_files: int = 50
    intake_zip_max_total_size_mb: int = 500

    @property
    def intake_allowed_extensions_set(self) -> set[str]:
        return {
            ext.strip().lower()
            for ext in self.intake_allowed_extensions.split(",")
            if ext.strip()
        }

    @property
    def intake_max_file_size_bytes(self) -> int:
        return self.intake_max_file_size_mb * 1024 * 1024

    @property
    def intake_zip_max_total_size_bytes(self) -> int:
        return self.intake_zip_max_total_size_mb * 1024 * 1024

    # ------------------------------------------------------------------
    # Phase 5 Step 25 - Billing/Subscription (app/billing/). "manual"
    # (default) needs no external payment gateway - see
    # app/billing/provider.py's ManualPaymentProvider.
    # ------------------------------------------------------------------
    billing_provider: str = "manual"
    # BILLING_PROVIDER=stripe: the secret key (sk_live_/sk_test_), the webhook
    # endpoint's signing secret (whsec_), and optionally the plan a tenant drops to
    # when its paid subscription ends (e.g. "free"; empty = keep the plan, marked canceled).
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_fallback_plan_slug: str = ""
    stripe_api_base: str = "https://api.stripe.com"  # e.g. http://localhost:12111 for stripe-mock in development
    # Who may create plans / set their Stripe prices (comma-separated emails). Plans
    # are shared by every organization, so with Stripe on this must be set - otherwise
    # any organization's owner could create itself a free unlimited plan.
    billing_plan_admin_emails: str = ""

    # ------------------------------------------------------------------
    # End-user accounts (app/security/end_user_accounts.py) - the Owner
    # invites each email; the user signs up once with a one-time code
    # sent to that inbox, then logs in with email + password.
    # ------------------------------------------------------------------
    end_user_token_expire_minutes: int = 480
    verification_code_expire_minutes: int = 10
    # Where the "create your account" link in invite emails points.
    frontend_base_url: str = "http://localhost:3000"

    # How verification codes/invites are delivered (app/notifications/email_sender.py):
    #   "console" (default) - printed to the API server's terminal, for
    #       local testing only; refused when ENVIRONMENT=production.
    #   "smtp" - a real mail server. For a Gmail sender: SMTP_HOST=smtp.gmail.com,
    #       SMTP_PORT=587, SMTP_USERNAME=<the gmail address>, SMTP_PASSWORD=<a
    #       Google "App Password", not the account password>.
    email_provider: str = "console"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True

    def resolve(self, relative_path: str) -> Path:
        """Resolve a configured path relative to the project root."""

        path = Path(relative_path)
        return path if path.is_absolute() else PROJECT_ROOT / path


@lru_cache
def get_settings() -> Settings:
    settings = Settings()

    if not settings.jwt_secret_key:
        raise RuntimeError(
            "JWT_SECRET_KEY must be set (.env) - refusing to start with no signing key."
        )

    return settings