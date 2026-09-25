from pydantic import BaseModel, EmailStr, Field, field_validator


class CategoryCreateRequest(BaseModel):
    """
    Body for POST /categories.

    A category is just a folder under storage/originals used to
    group uploaded documents (e.g. "Contracts", "HR Policies").
    """

    name: str = Field(..., min_length=1, max_length=100)
    parent: str | None = Field(
        None,
        description=(
            "Optional parent category path to nest this category "
            "under, e.g. parent='Contracts' with name='2024' creates "
            "the subfolder 'Contracts/2024'."
        ),
    )


class CategoryInfo(BaseModel):
    name: str
    document_count: int


class CategoryListResponse(BaseModel):
    categories: list[CategoryInfo]


class UploadedFileResult(BaseModel):
    filename: str
    category: str
    status: str
    reason: str
    size: int | None = None
    sha256: str | None = None


class UploadResponse(BaseModel):
    category: str
    results: list[UploadedFileResult]
    total_uploaded: int
    total_stored: int
    total_rejected: int


class DocumentInfo(BaseModel):
    filename: str
    category: str
    relative_path: str
    extension: str
    size: int
    status: str = "Uploaded"
    status_detail: str | None = None
    created_at: str


class DocumentListResponse(BaseModel):
    documents: list[DocumentInfo]
    total: int


class ProcessResult(BaseModel):
    """
    Summary counts from one completed processing job - the body
    POST /process used to return directly before processing became
    asynchronous. Now returned as the `result` field of
    GET /process/{job_id} once that job has finished.
    """

    documents_extracted: int
    documents_extraction_failed: int
    segments_created: int
    chunks_created: int
    embeddings_created: int
    # Chunks of deleted/replaced/moved files removed from the search index by this run.
    stale_chunks_removed: int = 0


class ProcessQueuedResponse(BaseModel):
    """Body for POST /process: the job has been enqueued, not run yet."""

    job_id: str
    status: str = "queued"


class ProcessStatusResponse(BaseModel):
    """
    Body for GET /process/{job_id}.

    `status` is one of RQ's job states: "queued", "started",
    "finished", "failed", "deferred", "scheduled", "stopped".
    `result` is populated once `status` is "finished"; `error` is
    populated once `status` is "failed".
    """

    job_id: str
    status: str
    result: ProcessResult | None = None
    error: str | None = None


class SearchRequest(BaseModel):
    """Body for POST /search."""

    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(5, ge=1, le=50)
    category: str | None = Field(
        None,
        description="Restrict results to one category (including its subfolders).",
    )


class SearchResultChunk(BaseModel):
    chunk_id: str
    document_id: str
    category: str
    filename: str
    chunk_text: str
    vector_score: float
    keyword_score: float
    final_score: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultChunk]


class OwnerResearchRequest(BaseModel):
    """
    Body for POST /research/ask - the Owner/Attorney/Paralegal-scope
    equivalent of POST /end-user/query/stream's real, citation-checked
    Claude answer (app/analysis/answer_generation.py), returned as a
    single response instead of Server-Sent Events. Never Matter-scoped
    - always the Owner's library only, same isolation guarantee as
    POST /search.
    """

    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int | None = Field(
        None, ge=1, le=50, description="Overrides the Owner-configured Top K for this request only."
    )
    category: str | None = Field(
        None, description="Restrict retrieval to one library category (including its subfolders)."
    )

    @field_validator("query")
    @classmethod
    def _sanitize_query(cls, value: str) -> str:
        from app.security.text_sanitization import sanitize_text

        return sanitize_text(value)


class OwnerResearchSource(BaseModel):
    filename: str
    category: str
    section: str | None = None
    start_page: int | None = None
    end_page: int | None = None
    score: float


class OwnerResearchResponse(BaseModel):
    query: str
    answer: str
    sources: list[OwnerResearchSource]

class OwnerResearchExportRequest(BaseModel):
    """
    Body for POST /research/export - renders an already-returned
    POST /research/ask result as a downloadable .docx or .pdf file.

    Never re-runs retrieval or Claude generation: the client sends
    back the exact answer and sources it already received (including
    the honest-gap case, where `sources` is empty and `answer` is the
    fixed "Insufficient information..." message), so the exported file
    can never drift from what the Owner actually saw on screen.
    """

    query: str = Field(..., min_length=1, max_length=1000)
    answer: str = Field(..., min_length=1)
    sources: list[OwnerResearchSource] = Field(default_factory=list)
    format: str = Field(..., description="'docx' or 'pdf'.")

    @field_validator("format")
    @classmethod
    def _validate_format(cls, value: str) -> str:
        if value not in ("docx", "pdf"):
            raise ValueError("format must be 'docx' or 'pdf'.")
        return value
# ---------------------------------------------------------------------
# End User API (app/api/end_user_api.py) - a separate scope from
# everything above, authenticated with X-End-User-Key instead of
# X-API-Key (see app/security/auth.py). Never exposes anything from
# the Owner/Admin surface (categories, raw documents, /process) -
# only search results and comparison-report content.
# ---------------------------------------------------------------------


class EndUserQueryRequest(BaseModel):
    """Body for POST /end-user/query."""

    query: str = Field(..., min_length=1, max_length=1000)

    @field_validator("query")
    @classmethod
    def _sanitize_query(cls, value: str) -> str:
        from app.security.text_sanitization import sanitize_text

        return sanitize_text(value)
    top_k: int | None = Field(
        None,
        ge=1,
        le=50,
        description="Overrides the Owner-configured Top K (GET /admin/retrieval-settings) for this request only.",
    )
    category: str | None = Field(
        None,
        description="Restrict results to one category (including its subfolders).",
    )
    thread_id: int | None = Field(
        None,
        description=(
            "POST /end-user/query/stream only: append this Q&A turn to an "
            "existing thread (POST /end-user/threads) instead of a one-off, "
            "stateless call. Must belong to the caller's own Matter."
        ),
    )


class EndUserQueryResultChunk(BaseModel):
    chunk_text: str
    filename: str
    category: str
    chapter: str | None = None
    section: str | None = None
    start_page: int | None = None
    end_page: int | None = None
    score: float


class EndUserQueryResponse(BaseModel):
    query: str
    results: list[EndUserQueryResultChunk]


class ProvenancedText(BaseModel):
    """
    A piece of report text, tagged with where it came from - part of
    the hallucination-control design (app/analysis/report_builder.py):
    every section of an AnalysisReport says plainly whether it's
    "retrieved" (a raw fact from the knowledge base), "generated"
    (prose interpreting that fact, written by whichever narrative
    provider is configured), or "recommendation" (actionable
    inference, not a retrieved fact).
    """

    text: str
    provenance: str


class SourceEvidenceSchema(BaseModel):
    """One cited piece of evidence: file name, page, section, chunk - see app/analysis/models.py."""

    filename: str
    category: str
    document_id: str
    chunk_id: str
    chunk_text: str
    chapter: str | None = None
    section: str | None = None
    start_page: int | None = None
    end_page: int | None = None
    score: float
    provenance: str = "retrieved"


class ComparisonItemSchema(BaseModel):
    """One chunk of the End User's submission compared against the knowledge base."""

    input_chunk_index: int
    input_text: str
    classification: str = Field(..., description='"match", "partial_match", or "gap"')
    top_score: float
    is_conflict: bool
    narrative: ProvenancedText
    sources: list[SourceEvidenceSchema]


class MatchScoreBreakdown(BaseModel):
    """
    What overall_match_score is made of - see
    app/analysis/matcher.py's module docstring for the formula. Always
    a defined, configurable computation - never LLM-estimated.
    """

    coverage_ratio: float
    avg_confidence: float
    coverage_weight: float
    confidence_weight: float


class DetailedMatching(BaseModel):
    similarities: list[ComparisonItemSchema]
    differences: list[ComparisonItemSchema]
    gaps: list[ComparisonItemSchema]
    conflicts: list[ComparisonItemSchema]


class AnalysisReport(BaseModel):
    """Body for POST /end-user/compare - see app/analysis/report_builder.py."""

    executive_summary: ProvenancedText
    overall_match_score: float
    match_score_breakdown: MatchScoreBreakdown
    detailed_matching: DetailedMatching
    recommendations: list[ProvenancedText]
    sources: list[SourceEvidenceSchema]
    insufficient_evidence: bool = Field(
        ...,
        description=(
            "True when nothing in the submission cleared even a partial-match "
            "threshold - executive_summary is then the fixed "
            "'Insufficient information found in the available knowledge base.' "
            "message, never LLM-generated."
        ),
    )
    provenance_legend: dict[str, str]


class CategoryRenameRequest(BaseModel):
    """Body for PATCH /categories/{category}."""

    new_name: str = Field(..., min_length=1, max_length=100)


class MessageResponse(BaseModel):
    """Generic confirmation response for delete/rename actions."""

    message: str


# ---------------------------------------------------------------------
# Disclaimer (app/disclaimer.py, app/metadata/base.py) - DB-backed, Owner-
# editable text shown on every DOCX/PDF analysis report export.
# ---------------------------------------------------------------------


class DisclaimerUpdateRequest(BaseModel):
    """Body for PUT /admin/disclaimer."""

    text: str = Field(..., min_length=1, max_length=5000)


class DisclaimerResponse(BaseModel):
    """Body for GET/PUT /admin/disclaimer."""

    text: str
    updated_at: str | None = None
    updated_by: str | None = None


# ---------------------------------------------------------------------
# Matters (app/metadata/base.py, app/security/auth.py) - isolated End
# User identities, each with its own X-End-User-Key and its own
# threads, invisible to every other Matter.
# ---------------------------------------------------------------------


class MatterCreateRequest(BaseModel):
    """Body for POST /admin/matters."""

    name: str = Field(..., min_length=1, max_length=255)


class MatterInfo(BaseModel):
    """One row of GET /admin/matters - never includes the API key, only its hash exists server-side."""

    id: int
    name: str
    is_active: bool
    created_at: str


class MatterListResponse(BaseModel):
    matters: list[MatterInfo]


class MatterCreatedResponse(BaseModel):
    """
    Body for POST /admin/matters. `api_key` is shown here in PLAINTEXT
    exactly once - only its SHA-256 hash is stored (app/security/auth.py's
    hash_api_key()), so it cannot be retrieved again after this response.
    """

    id: int
    name: str
    api_key: str
    created_at: str

class MatterAssignmentCreateRequest(BaseModel):
    """Body for POST /admin/matters/{matter_id}/assignments."""

    owner_id: int
    role: str = Field(..., description="'attorney' or 'paralegal'.")


class MatterAssignmentInfo(BaseModel):
    id: int
    owner_id: int
    matter_id: int
    role: str
    assigned_at: str


class MatterAssignmentListResponse(BaseModel):
    assignments: list[MatterAssignmentInfo]
# ---------------------------------------------------------------------
# Threads (app/metadata/base.py) - conversation history for
# POST /end-user/query/stream, isolated per Matter.
# ---------------------------------------------------------------------


class ThreadCreateRequest(BaseModel):
    """Body for POST /end-user/threads."""

    title: str = Field("New thread", max_length=255)


class ThreadInfo(BaseModel):
    id: int
    matter_id: int
    title: str
    created_at: str
    updated_at: str


class ThreadListResponse(BaseModel):
    threads: list[ThreadInfo]


class ThreadMessageInfo(BaseModel):
    id: int
    thread_id: int
    role: str
    content: str
    sources: list[dict] = Field(default_factory=list)
    created_at: str


class ThreadMessagesResponse(BaseModel):
    thread_id: int
    messages: list[ThreadMessageInfo]
# ---------------------------------------------------------------------
# Retrieval Settings (app/retrieval_settings.py, app/metadata/base.py) -
# DB-backed, Owner-editable Top K / score threshold / minimum chunks
# used by the hybrid retrieval pipeline (app/retrieval/retriever.py).
# ---------------------------------------------------------------------


class RetrievalSettingsUpdateRequest(BaseModel):
    """Body for PUT /admin/retrieval-settings."""

    top_k: int = Field(..., ge=1, le=50)
    score_threshold: float = Field(..., ge=0.0, le=1.0)
    min_chunks: int = Field(..., ge=0, le=50)


class RetrievalSettingsResponse(BaseModel):
    """Body for GET/PUT /admin/retrieval-settings."""

    top_k: int
    score_threshold: float
    min_chunks: int
    updated_at: str | None = None
    updated_by: str | None = None


# ---------------------------------------------------------------------
# Prompt Versions (app/prompts.py, app/metadata/base.py) - version
# history for the system prompts driving Claude-backed generation.
# ---------------------------------------------------------------------


class PromptVersionInfo(BaseModel):
    name: str
    version: int
    text: str
    is_active: bool
    created_at: str
    created_by: str | None = None


class PromptVersionListResponse(BaseModel):
    name: str
    versions: list[PromptVersionInfo]


class PromptVersionCreateRequest(BaseModel):
    """Body for POST /admin/prompts/{name} - creates and activates a new version."""

    text: str = Field(..., min_length=1, max_length=8000)


# ---------------------------------------------------------------------
# Phase 3 - Client Intake (app/api/intake_api.py, app/metadata/base.py) -
# a Matter's resumable guided-intake session: uploaded documents/images/
# audio/video/ZIP, their extracted content, a timeline, and generated
# reports (app/report/).
# ---------------------------------------------------------------------


class IntakeSessionCreateRequest(BaseModel):
    """Body for POST /end-user/intake/sessions."""

    title: str = Field("New intake", max_length=255)
    thread_id: int | None = Field(
        None, description="Optionally link this intake session to an existing thread (POST /end-user/threads)."
    )


class IntakeSessionInfo(BaseModel):
    id: int
    matter_id: int
    thread_id: int | None = None
    title: str
    status: str
    created_at: str
    updated_at: str


class IntakeSessionListResponse(BaseModel):
    sessions: list[IntakeSessionInfo]


class UploadedInputInfo(BaseModel):
    id: int
    intake_session_id: int
    original_filename: str
    media_type: str
    size: int
    processing_status: str
    status_detail: str | None = None
    created_at: str


class UploadedInputQueuedResponse(BaseModel):
    """Body for POST /end-user/intake/sessions/{id}/uploads."""

    uploaded_input: UploadedInputInfo
    job_id: str
    status: str = "queued"


class ExtractedInformationInfo(BaseModel):
    id: int
    content_type: str
    text: str
    provider: str
    is_mock: bool
    archive_member_filename: str | None = None
    created_at: str


class UploadedInputDetailResponse(BaseModel):
    """Body for GET /end-user/intake/uploads/{upload_id}."""

    uploaded_input: UploadedInputInfo
    extracted_information: list[ExtractedInformationInfo]


class IntakeUploadListResponse(BaseModel):
    """Body for GET /end-user/intake/sessions/{id}/uploads - every upload in the session, each with whatever has been extracted from it so far."""

    uploads: list[UploadedInputDetailResponse]


class TimelineEventInfo(BaseModel):
    id: int
    event_type: str
    description: str
    created_at: str


class IntakeTimelineResponse(BaseModel):
    intake_session_id: int
    events: list[TimelineEventInfo]


class ReportGenerateRequest(BaseModel):
    """Body for POST /end-user/intake/sessions/{id}/report."""

    format: str = Field(..., description="'docx', 'pdf', or 'image'.")


class ReportInfo(BaseModel):
    """Body for POST /end-user/intake/sessions/{id}/report."""

    id: int
    intake_session_id: int
    format: str
    created_at: str


# ---------------------------------------------------------------------
# Guided Intake Engine (app/intake_engine/, app/api/interview_api.py) -
# a conversational, state-machine-driven interview layered on top of
# an intake session: language selection, terms acceptance, a mandatory
# ancillary sweep, a protected-activity section, and a closing
# narrative - fully resumable via GET .../interview.
# ---------------------------------------------------------------------


class InterviewMessageInfo(BaseModel):
    id: int
    role: str
    content: str
    created_at: str


class InterviewStateInfo(BaseModel):
    intake_session_id: int
    language: str | None = None
    terms_accepted_at: str | None = None
    terms_version: str | None = None
    current_state: str
    current_step_index: int
    mandatory_sweep_completed: bool
    # "Question X of Y" - the interview is a fixed number of questions (see
    # app/intake_engine/state_machine.py's TOTAL_QUESTIONS). question_number
    # is None before the questions start and after the interview completes.
    question_number: int | None = None
    total_questions: int


class InterviewStartResponse(BaseModel):
    """Body for POST /end-user/intake/sessions/{id}/interview/start."""

    state: InterviewStateInfo
    prompt: str


class InterviewMessageRequest(BaseModel):
    """Body for POST /end-user/intake/sessions/{id}/interview/message."""

    message: str = Field(..., min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def _sanitize_message(cls, value: str) -> str:
        from app.security.text_sanitization import sanitize_text

        return sanitize_text(value)


class InterviewMessageResponse(BaseModel):
    """Body for POST /end-user/intake/sessions/{id}/interview/message."""

    state: InterviewStateInfo
    reply: str
    error: bool
    done: bool


class InterviewResumeResponse(BaseModel):
    """Body for GET /end-user/intake/sessions/{id}/interview - the resume endpoint."""

    state: InterviewStateInfo
    messages: list[InterviewMessageInfo]


class InterviewFactInfo(BaseModel):
    id: int
    category: str
    fact_key: str
    fact_value: str
    created_at: str


class InterviewFactsResponse(BaseModel):
    intake_session_id: int
    facts: list[InterviewFactInfo]


class MatterIntakeSessionDetailResponse(BaseModel):
    """
    Body for GET /admin/matters/{matter_id}/intake-sessions/{session_id} -
    everything the Owner needs to see about one Client's intake within
    a Matter: the session itself, its timeline, uploaded documents,
    recorded facts, and any generated reports. Reuses the exact same
    schemas the Client's own view of this data already returns (see
    app/api/intake_api.py, app/api/interview_api.py) - never a second,
    drifting representation of the same rows.
    """

    session: IntakeSessionInfo
    timeline: list[TimelineEventInfo]
    uploaded_inputs: list[UploadedInputInfo]
    facts: list[InterviewFactInfo]
    reports: list[ReportInfo]


class MatterResearchSuggestionCitation(BaseModel):
    filename: str
    category: str
    section: str | None = None
    start_page: int | None = None
    end_page: int | None = None
    score: float


class MatterResearchSuggestion(BaseModel):
    """
    One Matter fact and the knowledge-base material retrieval found for
    it - a suggestion for further research, never a cited legal
    authority and never a legal conclusion. Reuses
    app/report/rag_analysis.py's gather_fact_support() - the exact same
    retrieval-grounded fact classification the Client Report already
    runs - rather than a second implementation.
    """

    fact_text: str
    classification: str
    citations: list[MatterResearchSuggestionCitation]


class MatterResearchSuggestionsResponse(BaseModel):
    intake_session_id: int
    matter_id: int
    suggestions: list[MatterResearchSuggestion]
    disclaimer: str = (
        "These are retrieval-based research suggestions generated from this Matter's own intake facts, "
        "not cited legal authority and not a legal conclusion. They must be independently verified by an "
        "attorney before being relied upon or cited."
    )

# ---------------------------------------------------------------------
# Report Review Queue (app/api/storage_api.py, app/api/intake_api.py) -
# every generated Client-intake report starts 'pending_review' and
# must be approved by the Owner before an End User can download it.
# ---------------------------------------------------------------------


class PendingReportInfo(BaseModel):
    report_id: int
    intake_session_id: int
    format: str
    created_at: str
    status: str


class ReportReviewListResponse(BaseModel):
    reports: list[PendingReportInfo]


class ReportRejectRequest(BaseModel):
    """Body for POST /admin/reports/{report_id}/reject."""

    reason: str = Field(..., min_length=1, max_length=2000)


class ReportReviewInfo(BaseModel):
    """Body for POST /admin/reports/{report_id}/approve and .../reject."""

    report_id: int
    status: str
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    rejection_reason: str | None = None

class CauseOfActionCreateRequest(BaseModel):
    """Body for POST /admin/causes-of-action - Owner/attorney curation only."""

    category: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    elements: list[str] = Field(..., min_length=1)
    authority_citation: str = Field(..., min_length=1)


class CauseOfActionInfo(BaseModel):
    id: int
    category: str
    name: str
    elements: list[str]
    authority_citation: str
    created_at: str


class CauseOfActionListResponse(BaseModel):
    causes_of_action: list[CauseOfActionInfo]


class ComplaintGenerateRequest(BaseModel):
    """Body for POST /admin/intake/sessions/{id}/complaint."""

    cause_of_action_ids: list[int] = Field(..., min_length=1)
    format: str = Field(default="docx", description="'docx' (or 'pdf' once ComplaintPdfRenderer is added).")


class ComplaintInfo(BaseModel):
    id: int
    intake_session_id: int
    matter_id: int
    format: str
    cause_of_action_ids: list[int]
    created_at: str


class ComplaintPreviewSection(BaseModel):
    heading: str
    paragraphs: list[str]


class ComplaintDraftResponse(BaseModel):
    id: int
    intake_session_id: int
    matter_id: int
    format: str
    cause_of_action_ids: list[int]
    created_at: str
    sections: list[ComplaintPreviewSection]


class ComplaintListResponse(BaseModel):
    complaints: list[ComplaintInfo]


# ----------------------------------------------------------------------
# Billing / Subscription (Phase 5 Step 25 - app/billing/)
# ----------------------------------------------------------------------

class PlanInfo(BaseModel):
    id: int
    slug: str
    name: str
    description: str | None = None
    price_cents: int
    billing_interval: str
    max_matters: int | None = None
    max_documents: int | None = None
    max_storage_bytes: int | None = None
    max_llm_calls_per_month: int | None = None
    max_owners: int | None = None
    is_active: bool
    created_at: str


class PlanListResponse(BaseModel):
    plans: list[PlanInfo]


class PlanCreateRequest(BaseModel):
    """Body for POST /admin/billing/plans - defines a plan's configurable limits/entitlements. A limit left unset (null) means unlimited."""

    slug: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    price_cents: int = Field(default=0, ge=0)
    billing_interval: str = Field(default="monthly")
    max_matters: int | None = Field(default=None, ge=0)
    max_documents: int | None = Field(default=None, ge=0)
    max_storage_bytes: int | None = Field(default=None, ge=0)
    max_llm_calls_per_month: int | None = Field(default=None, ge=0)
    max_owners: int | None = Field(default=None, ge=0)

    @field_validator("billing_interval")
    @classmethod
    def _validate_billing_interval(cls, value: str) -> str:
        if value not in ("monthly", "yearly"):
            raise ValueError("billing_interval must be 'monthly' or 'yearly'")
        return value


class SubscriptionInfo(BaseModel):
    tenant_id: int
    status: str
    current_period_start: str
    current_period_end: str
    trial_end: str | None = None
    canceled_at: str | None = None
    plan: PlanInfo


class SubscribeRequest(BaseModel):
    """Body for POST /admin/billing/subscription - assigns the caller's tenant to a plan."""

    plan_slug: str = Field(..., min_length=1)
    trial_days: int | None = Field(default=None, ge=1)


class ChangePlanRequest(BaseModel):
    """Body for PUT /admin/billing/subscription - moves the caller's tenant's EXISTING subscription to a different plan."""

    plan_slug: str = Field(..., min_length=1)


class UsageInfo(BaseModel):
    matters: int
    documents: int
    storage_bytes: int
    llm_calls_per_month: int


class PlanLimitsInfo(BaseModel):
    max_matters: int | None = None
    max_documents: int | None = None
    max_storage_bytes: int | None = None
    max_llm_calls_per_month: int | None = None


class BillingUsageResponse(BaseModel):
    usage: UsageInfo
    limits: PlanLimitsInfo | None = Field(
        default=None,
        description="The active plan's limits for each resource - a null field means that resource is unlimited. The whole object is null if the tenant has no subscription.",
    )

# ----------------------------------------------------------------------
# End-user accounts (app/security/end_user_accounts.py, app/api/users_api.py,
# app/api/end_user_auth_api.py)
# ----------------------------------------------------------------------

class EndUserAccountInfo(BaseModel):
    id: int
    email: str
    status: str
    invited_by: str | None = None
    created_at: str
    activated_at: str | None = None


class EndUserListResponse(BaseModel):
    users: list[EndUserAccountInfo]


class InviteEndUsersRequest(BaseModel):
    """Body for POST /admin/users - one or more employee emails to invite."""

    emails: list[EmailStr] = Field(..., min_length=1, max_length=500)


class InviteSkippedEmail(BaseModel):
    email: str
    reason: str


class InviteEndUsersResponse(BaseModel):
    invited: list[EndUserAccountInfo]
    skipped: list[InviteSkippedEmail]


class EndUserEmailRequest(BaseModel):
    email: EmailStr


class EndUserSignupCompleteRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")
    password: str = Field(..., min_length=8, max_length=128)


class EndUserPasswordResetCompleteRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(..., min_length=8, max_length=128)


class EndUserLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class EndUserSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    email: str


class EndUserMeResponse(BaseModel):
    id: int
    email: str
    status: str


class GenericMessageResponse(BaseModel):
    detail: str
