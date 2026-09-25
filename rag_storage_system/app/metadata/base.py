"""
Metadata repository interface.

Same abstraction principle as app/storage/base.py: everything that
tracks folders/documents in a database (not the files themselves - see
StorageBackend for that) goes through an object that implements
MetadataRepository, instead of any caller talking to sqlite3/psycopg
directly. app/api/storage_api.py only ever calls methods defined here,
so swapping SQLiteMetadataRepository for PostgresMetadataRepository -
or back, for a fast local/test run - is a factory change in
app/metadata/__init__.py, not an endpoint rewrite.
"""

from abc import ABC, abstractmethod
from typing import Optional


class MetadataRepository(ABC):
    """Abstract base class for all metadata repository backends."""

    # ------------------------------------------------------------------
    # Folders
    # ------------------------------------------------------------------

    @abstractmethod
    def create_folder(self, path: str, tenant_id: int = 1) -> None:
        """Ensure `path` and every ancestor folder has a row, owned by `tenant_id`."""
        raise NotImplementedError

    @abstractmethod
    def rename_folder(self, old_path: str, new_path: str, tenant_id: int = 1) -> None:
        """
        Rename/move a folder, cascading to every descendant folder and
        document whose path/category starts with `old_path` - scoped to
        `tenant_id` only, never touching another tenant's folder tree.
        """
        raise NotImplementedError

    @abstractmethod
    def delete_folder(self, path: str, tenant_id: int = 1) -> None:
        """Delete a folder, its descendant folders, and their documents - scoped to `tenant_id`."""
        raise NotImplementedError

    @abstractmethod
    def list_folders(self, tenant_id: int = 1) -> list[dict]:
        """Returns `tenant_id`'s folders as a list of {"name": str, "document_count": int}."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    @abstractmethod
    def upsert_document(
        self,
        category: str,
        filename: str,
        extension: str,
        size: int,
        sha256: Optional[str],
        status: str = "Uploaded",
        status_detail: Optional[str] = None,
        tenant_id: int = 1,
    ) -> None:
        """Insert a document row (owned by `tenant_id`), or update it in place if it already exists."""
        raise NotImplementedError

    @abstractmethod
    def delete_document(self, category: str, filename: str, tenant_id: int = 1) -> bool:
        """Returns True if a row existed for `tenant_id` and was deleted, False otherwise."""
        raise NotImplementedError

    @abstractmethod
    def get_document(self, category: str, filename: str, tenant_id: int = 1) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def list_documents(self, category: Optional[str] = None, tenant_id: int = 1) -> list[dict]:
        """List `tenant_id`'s documents, optionally filtered to one category (including its subfolders)."""
        raise NotImplementedError

    @abstractmethod
    def update_document_status(
        self,
        category: str,
        filename: str,
        status: str,
        status_detail: Optional[str] = None,
        tenant_id: int = 1,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    def update_status_where(self, old_status: str, new_status: str) -> int:
        """Bulk-transition every document in `old_status` to `new_status`. Returns the count changed."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Disclaimer
    # ------------------------------------------------------------------

    @abstractmethod
    def get_disclaimer(self, tenant_id: int = 1) -> Optional[dict]:
        """
        Returns `tenant_id`'s Owner-edited disclaimer as
        {"text": str, "updated_at": ..., "updated_by": Optional[str]},
        or None if that organization has never saved one yet.
        """
        raise NotImplementedError

    @abstractmethod
    def update_disclaimer(self, text: str, updated_by: Optional[str] = None, tenant_id: int = 1) -> dict:
        """Create or replace `tenant_id`'s disclaimer and return it."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Retrieval Settings
    # ------------------------------------------------------------------

    @abstractmethod
    def get_retrieval_settings(self, tenant_id: int = 1) -> Optional[dict]:
        """
        Returns `tenant_id`'s Owner-edited retrieval settings as
        {"top_k": int, "score_threshold": float, "min_chunks": int,
        "updated_at": ..., "updated_by": Optional[str]}, or None if
        the Owner has never saved any yet.
        """
        raise NotImplementedError

    @abstractmethod
    def update_retrieval_settings(
        self,
        top_k: int,
        score_threshold: float,
        min_chunks: int,
        updated_by: Optional[str] = None,
        tenant_id: int = 1,
    ) -> dict:
        """Create or replace `tenant_id`'s retrieval settings and return them."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Threads (isolated per matter - see app/matters.py)
    # ------------------------------------------------------------------

    @abstractmethod
    def create_thread(self, matter_id: int, title: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def list_threads(self, matter_id: int) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def get_thread(self, thread_id: int, matter_id: int) -> Optional[dict]:
        """None if the thread doesn't exist OR belongs to a different matter - isolation lives here."""
        raise NotImplementedError

    @abstractmethod
    def add_thread_message(
        self, thread_id: int, role: str, content: str, sources_json: Optional[str] = None
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    def list_thread_messages(self, thread_id: int) -> list[dict]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Matters (isolated End User identities - see app/security/auth.py)
    # ------------------------------------------------------------------

    @abstractmethod
    def get_matter_by_key_hash(self, api_key_hash: str) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def create_matter(self, name: str, api_key_hash: str, tenant_id: int = 1) -> dict:
        raise NotImplementedError

    @abstractmethod
    def list_matters(self, tenant_id: int = 1) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def get_matter(self, matter_id: int) -> Optional[dict]:
        """Look up a Matter by id (Owner-side; no api_key_hash needed) - used by role-based access checks."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Matter Assignments (role-based access - see app/security/auth.py's
    # ensure_matter_access())
    # ------------------------------------------------------------------

    @abstractmethod
    def create_matter_assignment(self, owner_id: int, matter_id: int, role: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def get_matter_assignment(self, owner_id: int, matter_id: int) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def list_assignments_for_matter(self, matter_id: int) -> list[dict]:
        raise NotImplementedError
    # ------------------------------------------------------------------
    # Prompt Versions
    # ------------------------------------------------------------------

    @abstractmethod
    def get_active_prompt_version(self, name: str, tenant_id: int = 1) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def list_prompt_versions(self, name: str, tenant_id: int = 1) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def create_prompt_version(
        self, name: str, text: str, created_by: Optional[str] = None, tenant_id: int = 1
    ) -> dict:
        """Inserts the next version for `name` within `tenant_id`, deactivates the previous active one, activates this one."""
        raise NotImplementedError

    @abstractmethod
    def activate_prompt_version(self, name: str, version: int, tenant_id: int = 1) -> dict:
        """Rollback/roll-forward: makes an existing version active again, within `tenant_id`."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Intake Sessions (Phase 3 - app/multimodal/, app/report/)
    # ------------------------------------------------------------------

    @abstractmethod
    def create_intake_session(self, matter_id: int, title: str, thread_id: Optional[int] = None) -> dict:
        raise NotImplementedError

    @abstractmethod
    def list_intake_sessions(self, matter_id: int) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def get_intake_session(self, session_id: int, matter_id: int) -> Optional[dict]:
        """None if it doesn't exist OR belongs to a different matter - isolation lives here, same as get_thread()."""
        raise NotImplementedError

    @abstractmethod
    def get_intake_session_by_id(self, session_id: int) -> Optional[dict]:
        """
        Unfiltered lookup (no matter_id isolation check) - only for
        internal callers that already have the session's own id from a
        trusted source (app/report/builder.py, app/api/complaint_api.py),
        never from a user-supplied cross-tenant id.
        """
        raise NotImplementedError

    @abstractmethod
    def update_intake_session_status(self, session_id: int, status: str) -> bool:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Uploaded Inputs
    # ------------------------------------------------------------------

    @abstractmethod
    def create_uploaded_input(
        self,
        intake_session_id: int,
        original_filename: str,
        stored_category: str,
        stored_filename: str,
        media_type: str,
        size: int,
        sha256: Optional[str],
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    def get_uploaded_input(self, input_id: int) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def list_uploaded_inputs(self, intake_session_id: int) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def update_uploaded_input_status(
        self, input_id: int, processing_status: str, status_detail: Optional[str] = None
    ) -> bool:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Extracted Information
    # ------------------------------------------------------------------

    @abstractmethod
    def add_extracted_information(
        self,
        uploaded_input_id: int,
        content_type: str,
        text: str,
        provider: str,
        is_mock: bool,
        archive_member_filename: Optional[str] = None,
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    def list_extracted_information(self, uploaded_input_id: int) -> list[dict]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------

    @abstractmethod
    def add_timeline_event(self, intake_session_id: int, event_type: str, description: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def list_timeline_events(self, intake_session_id: int) -> list[dict]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    @abstractmethod
    def create_report(
        self, intake_session_id: int, format: str, stored_category: str, stored_filename: str
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    def get_report(self, report_id: int) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def list_reports(self, intake_session_id: int) -> list[dict]:
        raise NotImplementedError
        # ------------------------------------------------------------------
    # Guided Intake Engine - Interview State (Phase 3 - app/intake_engine/)
    # ------------------------------------------------------------------

    @abstractmethod
    def create_interview_state(self, intake_session_id: int) -> dict:
        raise NotImplementedError

    @abstractmethod
    def get_interview_state(self, intake_session_id: int) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def update_interview_state(
        self,
        intake_session_id: int,
        language: Optional[str],
        current_state: str,
        current_step_index: int,
        terms_accepted_at: Optional[str],
        terms_version: Optional[str],
        mandatory_sweep_completed: bool,
    ) -> dict:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Guided Intake Engine - Messages
    # ------------------------------------------------------------------

    @abstractmethod
    def add_intake_message(self, intake_session_id: int, role: str, content: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def list_intake_messages(self, intake_session_id: int) -> list[dict]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Guided Intake Engine - Facts
    # ------------------------------------------------------------------

    @abstractmethod
    def add_intake_fact(self, intake_session_id: int, category: str, fact_key: str, fact_value: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def list_intake_facts(self, intake_session_id: int, category: Optional[str] = None) -> list[dict]:
        raise NotImplementedError
        # ------------------------------------------------------------------
    # Report Review Queue (Owner approval gate for Client-facing reports)
    # ------------------------------------------------------------------

    @abstractmethod
    def create_report_review(self, report_id: int) -> dict:
        raise NotImplementedError

    @abstractmethod
    def get_report_review(self, report_id: int) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def list_report_reviews(self, status: Optional[str] = None) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def update_report_review(
        self, report_id: int, status: str, reviewed_by: Optional[str] = None, rejection_reason: Optional[str] = None
    ) -> dict:
        raise NotImplementedError
        # ------------------------------------------------------------------
    # Cause of Action Library (Owner-curated legal elements/authority -
    # see app/complaint/builder.py)
    # ------------------------------------------------------------------

    @abstractmethod
    def create_cause_of_action(
        self, category: str, name: str, elements: list[str], authority_citation: str, tenant_id: int = 1
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    def get_cause_of_action(self, cause_of_action_id: int, tenant_id: int = 1) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def list_causes_of_action(self, category: Optional[str] = None, tenant_id: int = 1) -> list[dict]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Complaints (app/complaint/)
    # ------------------------------------------------------------------

    @abstractmethod
    def create_complaint(
        self,
        intake_session_id: int,
        matter_id: int,
        format: str,
        cause_of_action_ids: list[int],
        stored_category: str,
        stored_filename: str,
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    def get_complaint(self, complaint_id: int) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def list_complaints(self, intake_session_id: int) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def add_llm_usage_log(
        self, matter_id: Optional[int], intake_session_id: Optional[int], purpose: str,
        model: str, input_tokens: int, output_tokens: int, latency_ms: int,
        query_text: Optional[str] = None, retrieved_chunk_ids: Optional[list] = None,
        retrieved_chunk_scores: Optional[list] = None, citation_check_result: Optional[str] = None,
        tenant_id: int = 1,
    ) -> dict:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Vault sync (migration 0022) and duplicate detection
    # ------------------------------------------------------------------

    @abstractmethod
    def find_document_by_sha256(self, sha256: str, tenant_id: int) -> Optional[dict]:
        """Any of `tenant_id`'s documents with exactly this content, or None."""
        raise NotImplementedError

    @abstractmethod
    def list_vault_manifest(self, tenant_id: int) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def upsert_vault_manifest(
        self, tenant_id: int, source_path: str, category: str, filename: str, sha256: str, size: int, mtime: float
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_vault_manifest(self, tenant_id: int, source_path: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def add_vault_sync_run(self, tenant_id: int, run: dict) -> dict:
        """`run`: source, status, added, updated, deleted, unchanged, skipped (list), error, started_at."""
        raise NotImplementedError

    @abstractmethod
    def latest_vault_sync_run(self, tenant_id: int) -> Optional[dict]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Owner research threads (migration 0021) - always scoped to one
    # organization AND the admin user who owns the thread (owner_sub).
    # ------------------------------------------------------------------

    @abstractmethod
    def create_research_thread(self, tenant_id: int, owner_sub: str, title: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def list_research_threads(self, tenant_id: int, owner_sub: str) -> list[dict]:
        """Newest-updated first, each with a message_count."""
        raise NotImplementedError

    @abstractmethod
    def get_research_thread(self, thread_id: int, tenant_id: int, owner_sub: str) -> Optional[dict]:
        """None unless the thread belongs to exactly this tenant AND owner."""
        raise NotImplementedError

    @abstractmethod
    def rename_research_thread(self, thread_id: int, tenant_id: int, owner_sub: str, title: str) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def delete_research_thread(self, thread_id: int, tenant_id: int, owner_sub: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def add_research_exchange(self, thread_id: int, question: str, answer: str, sources: list[dict]) -> None:
        """Append one question + its answer (with its locked sources) and bump the thread's updated_at."""
        raise NotImplementedError

    @abstractmethod
    def list_research_messages(self, thread_id: int) -> list[dict]:
        """Oldest first; `sources` decoded to a list."""
        raise NotImplementedError

    @abstractmethod
    def list_llm_usage_log(
        self, tenant_id: int, limit: int = 50, offset: int = 0, questions_only: bool = False
    ) -> tuple[list[dict], int]:
        """
        `tenant_id`'s llm_usage_log rows, newest first, and the total count.
        `questions_only` keeps just the answered questions (rows with a
        query_text) - leaving out narrative/vision/relevance-check calls.
        retrieved_chunk_ids/scores come back as lists.
        """
        raise NotImplementedError

    @abstractmethod
    def count_llm_usage_since(self, tenant_id: int, since: str) -> int:
        """Count llm_usage_log rows for `tenant_id` created at/after `since` (an ISO-8601 timestamp) - the current billing period's LLM-call usage."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Billing: Plans (app/billing/) - a global catalog, not tenant-owned.
    # A NULL/None limit column means "unlimited" - see app/billing/service.py.
    # ------------------------------------------------------------------

    @abstractmethod
    def create_plan(
        self, slug: str, name: str, description: Optional[str] = None, price_cents: int = 0,
        billing_interval: str = "monthly", max_matters: Optional[int] = None,
        max_documents: Optional[int] = None, max_storage_bytes: Optional[int] = None,
        max_llm_calls_per_month: Optional[int] = None, max_owners: Optional[int] = None,
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    def get_plan(self, plan_id: int) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def get_plan_by_slug(self, slug: str) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def list_plans(self, active_only: bool = False) -> list[dict]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Billing: Tenant Subscriptions (app/billing/) - exactly one row per
    # tenant, linking it to its current plan and status.
    # ------------------------------------------------------------------

    @abstractmethod
    def create_tenant_subscription(
        self, tenant_id: int, plan_id: int, status: str, current_period_start: str,
        current_period_end: str, trial_end: Optional[str] = None, provider: Optional[str] = None,
        provider_customer_id: Optional[str] = None, provider_subscription_id: Optional[str] = None,
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    def get_subscription_for_tenant(self, tenant_id: int) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def update_subscription_status(
        self, tenant_id: int, status: str, canceled_at: Optional[str] = None
    ) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def change_tenant_plan(
        self, tenant_id: int, plan_id: int, current_period_start: str, current_period_end: str
    ) -> Optional[dict]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # End-user accounts (app/security/end_user_accounts.py). Emails are
    # always stored and looked up already normalized (lowercase,
    # stripped) - callers normalize, repositories don't.
    # ------------------------------------------------------------------

    @abstractmethod
    def create_end_user_invite(self, email: str, tenant_id: int, invited_by: Optional[str]) -> dict:
        raise NotImplementedError

    @abstractmethod
    def get_end_user(self, end_user_id: int) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def get_end_user_by_email(self, email: str) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def list_end_users(self, tenant_id: int) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def activate_end_user(self, end_user_id: int, password_hash: str, matter_id: int, activated_at) -> dict:
        raise NotImplementedError

    @abstractmethod
    def update_end_user_password(self, end_user_id: int, password_hash: str) -> dict:
        """Sets a new password AND bumps session_version, so every existing session for this account stops working."""
        raise NotImplementedError

    @abstractmethod
    def set_end_user_status(self, end_user_id: int, status: str) -> dict:
        """Sets status AND bumps session_version, so a deactivation takes effect on every existing session immediately."""
        raise NotImplementedError

    @abstractmethod
    def create_verification_code(self, email: str, purpose: str, code_hash: str, expires_at) -> dict:
        """Stores a new code for (email, purpose), invalidating any earlier unconsumed one for the same pair."""
        raise NotImplementedError

    @abstractmethod
    def get_latest_verification_code(self, email: str, purpose: str) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def increment_verification_attempts(self, code_id: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def consume_verification_code(self, code_id: int, consumed_at) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_tenant_resource_usage(self, tenant_id: int) -> dict:
        """{'matters': int, 'documents': int, 'storage_bytes': int} for `tenant_id` - the resources app/billing/service.py checks matter/document/storage plan limits against."""
        raise NotImplementedError