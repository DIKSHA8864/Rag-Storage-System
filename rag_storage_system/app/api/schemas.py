from pydantic import BaseModel, Field


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
    top_k: int = Field(5, ge=1, le=50)
    category: str | None = Field(
        None,
        description="Restrict results to one category (including its subfolders).",
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
