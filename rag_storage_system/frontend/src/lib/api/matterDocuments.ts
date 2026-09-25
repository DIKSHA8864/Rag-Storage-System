import { apiRequest, apiRequestBlob, apiRequestFormData } from "./client";
import type { MatterDocumentInfo, MatterDocumentListResponse } from "./types";

export async function listMatterDocuments(matterId: number, token: string): Promise<MatterDocumentListResponse> {
  return apiRequest<MatterDocumentListResponse>(`/admin/matters/${matterId}/documents`, { token });
}

export async function uploadMatterDocument(
  matterId: number,
  file: File,
  docType: string,
  token: string
): Promise<MatterDocumentInfo> {
  const form = new FormData();
  form.append("file", file);
  form.append("doc_type", docType);
  return apiRequestFormData<MatterDocumentInfo>(`/admin/matters/${matterId}/documents`, form, { token });
}

export async function downloadMatterDocument(matterId: number, documentId: number, token: string): Promise<Blob> {
  return apiRequestBlob(`/admin/matters/${matterId}/documents/${documentId}/download`, { token });
}

export async function reindexMatterDocument(matterId: number, documentId: number, token: string): Promise<MatterDocumentInfo> {
  return apiRequest<MatterDocumentInfo>(`/admin/matters/${matterId}/documents/${documentId}/reindex`, {
    method: "POST",
    token,
  });
}

export async function deleteMatterDocument(matterId: number, documentId: number, token: string): Promise<void> {
  await apiRequest(`/admin/matters/${matterId}/documents/${documentId}`, { method: "DELETE", token });
}
