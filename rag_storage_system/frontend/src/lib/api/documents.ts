import { apiRequest, apiRequestFormData } from "./client";
import type {
  CategoryCreateRequest,
  CategoryInfo,
  CategoryListResponse,
  DocumentListResponse,
  MessageResponse,
  ProcessQueuedResponse,
  ProcessStatusResponse,
  UploadResponse,
} from "./types";

// Categories are flat "Parent/Child" strings (see app/api/schemas.py's
// CategoryCreateRequest) - encoding each segment separately (instead
// of the whole path at once) keeps literal "/" characters as real
// path separators for FastAPI's {category:path} route parameter,
// while still safely encoding spaces/special characters within a
// single folder name.
function encodeCategoryPath(category: string): string {
  return category
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

export async function listCategories(token: string): Promise<CategoryListResponse> {
  return apiRequest<CategoryListResponse>("/categories", { token });
}

export async function createCategory(
  request: CategoryCreateRequest,
  token: string
): Promise<CategoryInfo> {
  return apiRequest<CategoryInfo>("/categories", {
    method: "POST",
    body: request,
    token,
  });
}

export async function listDocuments(
  token: string,
  category: string
): Promise<DocumentListResponse> {
  return apiRequest<DocumentListResponse>(`/documents?category=${encodeURIComponent(category)}`, {
    token,
  });
}

export async function uploadDocuments(
  category: string,
  files: File[],
  token: string
): Promise<UploadResponse> {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }

  return apiRequestFormData<UploadResponse>(
    `/categories/${encodeCategoryPath(category)}/documents/batch`,
    formData,
    { token }
  );
}

export async function deleteDocument(
  category: string,
  filename: string,
  token: string
): Promise<MessageResponse> {
  return apiRequest<MessageResponse>(
    `/categories/${encodeCategoryPath(category)}/documents/${encodeURIComponent(filename)}`,
    { method: "DELETE", token }
  );
}

export async function startProcessing(token: string): Promise<ProcessQueuedResponse> {
  return apiRequest<ProcessQueuedResponse>("/process", { method: "POST", token });
}

export async function getProcessingStatus(
  jobId: string,
  token: string
): Promise<ProcessStatusResponse> {
  return apiRequest<ProcessStatusResponse>(`/process/${encodeURIComponent(jobId)}`, { token });
}