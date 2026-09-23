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

export interface ApiErrorBody {
  detail?: string;
}