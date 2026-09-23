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

export interface ApiErrorBody {
  detail?: string;
}