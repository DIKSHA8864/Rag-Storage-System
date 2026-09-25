// Mirrors app/api/auth_api.py and app/api/schemas.py's response models
// exactly - keep these in sync with the backend, never invent fields
// the API doesn't actually return.

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface OwnerResearchRequest {
  query: string;
  top_k?: number;
  category?: string;
}

export interface OwnerResearchSource {
  filename: string;
  category: string;
  section: string | null;
  start_page: number | null;
  end_page: number | null;
  score: number;
  // The retrieved passage, verbatim.
  excerpt?: string | null;
  // The source file's one-line summary header.
  summary?: string | null;
}

export interface OwnerResearchResponse {
  query: string;
  answer: string;
  sources: OwnerResearchSource[];
}
export interface OwnerResearchExportRequest {
  query: string;
  answer: string;
  sources: OwnerResearchSource[];
  format: "docx" | "pdf";
}
export interface CategoryInfo {
  name: string;
  document_count: number;
}

export interface CategoryListResponse {
  categories: CategoryInfo[];
}

export interface CategoryCreateRequest {
  name: string;
  parent?: string;
}

export interface DocumentInfo {
  filename: string;
  category: string;
  relative_path: string;
  extension: string;
  size: number;
  status: string;
  status_detail?: string | null;
  created_at: string;
}

export interface DocumentListResponse {
  documents: DocumentInfo[];
  total: number;
}

export interface UploadedFileResult {
  filename: string;
  category: string;
  status: string;
  reason: string;
  size?: number | null;
  sha256?: string | null;
}

export interface UploadResponse {
  category: string;
  results: UploadedFileResult[];
  total_uploaded: number;
  total_stored: number;
  total_rejected: number;
}

export interface MessageResponse {
  message: string;
}

export interface ProcessQueuedResponse {
  job_id: string;
  status: string;
}

export interface ProcessResult {
  documents_extracted: number;
  documents_extraction_failed: number;
  segments_created: number;
  chunks_created: number;
  embeddings_created: number;
  stale_chunks_removed: number;
}

export interface ProcessStatusResponse {
  job_id: string;
  status: string;
  result?: ProcessResult | null;
  error?: string | null;
}

export interface AdminStats {
  total_documents: number;
  total_categories: number;
  storage_bytes: number;
  storage_mb: number;
  status_counts: {
    Uploaded: number;
    Processing: number;
    Embedding: number;
    Indexed: number;
    Failed: number;
  };
  last_synced_at: string | null;
}

export interface IntakeSessionCreateRequest {
  title?: string;
  thread_id?: number | null;
}

export interface IntakeSessionInfo {
  id: number;
  matter_id: number;
  thread_id: number | null;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface IntakeSessionListResponse {
  sessions: IntakeSessionInfo[];
}

export interface InterviewStateInfo {
  intake_session_id: number;
  language: string | null;
  terms_accepted_at: string | null;
  terms_version: string | null;
  current_state: string;
  current_step_index: number;
  mandatory_sweep_completed: boolean;
  // "Question X of Y" - null before the questions start and once complete.
  question_number: number | null;
  total_questions: number;
  // 2 = story first (every new interview); 1 = started before that, finishes on the old order.
  flow_version: number;
  // e.g. "story", "follow_up_2", "overtime", "date_hired", "documents".
  current_question_key: string | null;
  terms_accepted_ip: string | null;
}

export interface InterviewStartResponse {
  state: InterviewStateInfo;
  prompt: string;
}

export interface InterviewMessageResponse {
  state: InterviewStateInfo;
  reply: string;
  error: boolean;
  done: boolean;
}

export interface InterviewMessageInfo {
  id: number | string;
  role: string;
  content: string;
  created_at?: string;
}

export interface InterviewResumeResponse {
  state: InterviewStateInfo;
  messages: InterviewMessageInfo[];
}

export interface ReportGenerateRequest {
  format: "docx" | "pdf" | "image";
}

export interface ReportInfo {
  id: number;
  intake_session_id: number;
  format: string;
  created_at: string;
}

export interface PendingReportInfo {
  report_id: number;
  intake_session_id: number;
  format: string;
  created_at: string;
  status: string;
}

export interface ReportReviewListResponse {
  reports: PendingReportInfo[];
}

export interface ReportReviewInfo {
  report_id: number;
  status: string;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  rejection_reason?: string | null;
}

export interface MatterInfo {
  id: number;
  name: string;
  is_active: boolean;
  created_at: string;
  // "client" = a client's own matter; "case" = one case (a client's intake + the attorney's case documents).
  kind: string;
  client_email: string | null;
}

export interface MatterListResponse {
  matters: MatterInfo[];
}

export interface MatterCreateRequest {
  name: string;
}

export interface MatterCreatedResponse {
  id: number;
  name: string;
  api_key: string;
  created_at: string;
}

export interface TimelineEventInfo {
  id: number;
  event_type: string;
  description: string;
  created_at: string;
}

export interface UploadedInputInfo {
  id: number;
  intake_session_id: number;
  original_filename: string;
  media_type: string;
  size: number;
  processing_status: string;
  status_detail?: string | null;
  created_at: string;
}

export interface ExtractedInformationInfo {
  id: number;
  content_type: "text" | "ocr_text" | "transcript" | "caption" | "frame_caption" | string;
  text: string;
  provider: string;
  is_mock: boolean;
  archive_member_filename: string | null;
  created_at: string;
}

export interface UploadedInputDetailResponse {
  uploaded_input: UploadedInputInfo;
  extracted_information: ExtractedInformationInfo[];
}

export interface IntakeUploadListResponse {
  uploads: UploadedInputDetailResponse[];
}

export interface UploadedInputQueuedResponse {
  uploaded_input: UploadedInputInfo;
  job_id: string;
  status: string;
}

export interface InterviewFactInfo {
  id: number;
  category: string;
  fact_key: string;
  fact_value: string;
  created_at: string;
}

export interface MatterIntakeSessionDetailResponse {
  session: IntakeSessionInfo;
  timeline: TimelineEventInfo[];
  uploaded_inputs: UploadedInputInfo[];
  facts: InterviewFactInfo[];
  reports: ReportInfo[];
}

export interface CauseOfActionInfo {
  id: number;
  category: string;
  name: string;
  elements: string[];
  authority_citation: string;
  created_at: string;
}

export interface CauseOfActionListResponse {
  causes_of_action: CauseOfActionInfo[];
}

export interface CauseOfActionCreateRequest {
  category: string;
  name: string;
  elements: string[];
  authority_citation: string;
}

export interface ComplaintGenerateRequest {
  cause_of_action_ids: number[];
  format: "docx";
  // "pleading" = California pleading paper; "template" = the firm's own .docx (template_id); "plain" = simple draft.
  style?: "pleading" | "template" | "plain";
  template_id?: number | null;
  plaintiff_name?: string | null;
  defendant_name?: string | null;
  case_number?: string | null;
  county?: string | null;
}

export interface ComplaintInfo {
  id: number;
  intake_session_id: number;
  matter_id: number;
  format: string;
  cause_of_action_ids: number[];
  created_at: string;
}

export interface ComplaintPreviewSection {
  heading: string;
  paragraphs: string[];
}

export interface ComplaintDraftResponse extends ComplaintInfo {
  sections: ComplaintPreviewSection[];
}

export interface ComplaintListResponse {
  complaints: ComplaintInfo[];
}

export interface PromptVersionInfo {
  name: string;
  version: number;
  text: string;
  is_active: boolean;
  created_at: string;
  created_by: string | null;
}

export interface PromptVersionListResponse {
  name: string;
  versions: PromptVersionInfo[];
}

export interface PromptVersionCreateRequest {
  text: string;
}

export interface MatterResearchSuggestionCitation {
  filename: string;
  category: string;
  section: string | null;
  start_page: number | null;
  end_page: number | null;
  score: number;
}

export interface MatterResearchSuggestion {
  fact_text: string;
  classification: string;
  citations: MatterResearchSuggestionCitation[];
}

export interface MatterResearchSuggestionsResponse {
  intake_session_id: number;
  matter_id: number;
  suggestions: MatterResearchSuggestion[];
  disclaimer: string;
}

export interface ApiErrorBody {
  detail?: string;
}

export interface PlanInfo {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  price_cents: number;
  billing_interval: string;
  max_matters: number | null;
  max_documents: number | null;
  max_storage_bytes: number | null;
  max_llm_calls_per_month: number | null;
  max_owners: number | null;
  is_active: boolean;
  created_at: string;
}

export interface PlanListResponse {
  plans: PlanInfo[];
}

export interface PlanCreateRequest {
  slug: string;
  name: string;
  description?: string | null;
  price_cents?: number;
  billing_interval?: string;
  max_matters?: number | null;
  max_documents?: number | null;
  max_storage_bytes?: number | null;
  max_llm_calls_per_month?: number | null;
  max_owners?: number | null;
}

export interface SubscriptionInfo {
  tenant_id: number;
  status: string;
  current_period_start: string;
  current_period_end: string;
  trial_end: string | null;
  canceled_at: string | null;
  plan: PlanInfo;
}

export interface SubscribeRequest {
  plan_slug: string;
  trial_days?: number | null;
}

export interface ChangePlanRequest {
  plan_slug: string;
}

export interface UsageInfo {
  matters: number;
  documents: number;
  storage_bytes: number;
  llm_calls_per_month: number;
}

export interface PlanLimitsInfo {
  max_matters: number | null;
  max_documents: number | null;
  max_storage_bytes: number | null;
  max_llm_calls_per_month: number | null;
}

export interface BillingUsageResponse {
  usage: UsageInfo;
  limits: PlanLimitsInfo | null;
}
// ---------------------------------------------------------------------
// End-user accounts (app/api/users_api.py, app/api/end_user_auth_api.py)
// ---------------------------------------------------------------------

export interface EndUserAccountInfo {
  id: number;
  email: string;
  status: "invited" | "active" | "deactivated" | string;
  invited_by: string | null;
  created_at: string;
  activated_at: string | null;
}

export interface EndUserListResponse {
  users: EndUserAccountInfo[];
}

export interface InviteEndUsersResponse {
  invited: EndUserAccountInfo[];
  skipped: { email: string; reason: string }[];
}

export interface EndUserSessionResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  email: string;
}

export interface GenericMessageResponse {
  detail: string;
}

// Same shape the backend returns for Owner research sources (app/analysis/answer_generation.py's locked `sources`).
export type EndUserQuerySource = OwnerResearchSource;

// ---------------------------------------------------------------------
// Settings (GET/PUT /admin/retrieval-settings, /admin/disclaimer) and
// the Owner's question log (GET /admin/query-log) - all per organization.
// ---------------------------------------------------------------------

export interface RetrievalSettingsInfo {
  top_k: number;
  score_threshold: number;
  min_chunks: number;
  updated_at: string | null;
  updated_by: string | null;
}

export interface DisclaimerInfo {
  text: string;
  updated_at: string | null;
  updated_by: string | null;
}

export interface QueryLogEntry {
  id: number;
  created_at: string;
  purpose: string;
  query_text: string | null;
  model: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  citation_check_result: string | null;
  retrieved_count: number;
  top_score: number | null;
  matter_id: number | null;
}

export interface QueryLogResponse {
  entries: QueryLogEntry[];
  total: number;
}

// ---------------------------------------------------------------------
// Owner research threads (app/api/research_threads_api.py)
// ---------------------------------------------------------------------

export interface ResearchThreadInfo {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ResearchMessageInfo {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources: OwnerResearchSource[];
  created_at: string;
}

export interface ResearchThreadDetailResponse {
  thread: ResearchThreadInfo;
  messages: ResearchMessageInfo[];
}

// ---------------------------------------------------------------------
// Vault sync (app/api/vault_sync_api.py)
// ---------------------------------------------------------------------

export interface VaultSyncRunInfo {
  id: number;
  source: string;
  status: "ok" | "refused" | "failed" | string;
  added: number;
  updated: number;
  deleted: number;
  unchanged: number;
  skipped: { path: string; reason: string }[];
  error: string | null;
  started_at: string;
  finished_at: string;
}

export interface VaultSyncStatusResponse {
  configured: boolean;
  source: string | null;
  interval_seconds: number | null;
  last_run: VaultSyncRunInfo | null;
}

// Guided-intake checklist (app/api/intake_checklist_api.py).
export interface IntakeChecklistItem {
  key: string;
  prompt_en: string;
  prompt_es: string;
  is_active: boolean;
  required: boolean;
}

export interface IntakeChecklistResponse {
  items: IntakeChecklistItem[];
  customized: boolean;
  required_keys: string[];
}

// Attorney case documents (app/api/matter_documents_api.py).
export interface MatterDocumentInfo {
  id: number;
  matter_id: number;
  doc_type: string;
  original_filename: string;
  size: number;
  uploaded_by: string | null;
  status: "queued" | "indexed" | "failed";
  chunk_count: number;
  error: string | null;
  created_at: string;
}

export interface MatterDocumentListResponse {
  documents: MatterDocumentInfo[];
  doc_types: string[];
}

// Pleading details + firm templates (app/api/pleading_api.py).
export interface PleadingSettings {
  attorney_name: string;
  bar_number: string;
  firm_name: string;
  address: string;
  phone: string;
  email: string;
  attorney_for: string;
  court_name: string;
  county: string;
}

export interface PleadingSettingsResponse extends PleadingSettings {
  updated_at: string | null;
  updated_by: string | null;
}

export interface DocumentTemplateInfo {
  id: number;
  name: string;
  kind: string;
  original_filename: string;
  placeholders: string[];
  uploaded_by: string | null;
  created_at: string;
}

export interface DocumentTemplateListResponse {
  templates: DocumentTemplateInfo[];
  placeholders: string[];
}
