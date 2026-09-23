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
export interface ApiErrorBody {
  detail?: string;
}