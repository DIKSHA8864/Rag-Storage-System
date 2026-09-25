import { apiRequest, apiRequestBlob, apiRequestFormData } from "./client";
import type {
  DocumentTemplateInfo,
  DocumentTemplateListResponse,
  PleadingSettings,
  PleadingSettingsResponse,
} from "./types";

export async function getPleadingSettings(token: string): Promise<PleadingSettingsResponse> {
  return apiRequest<PleadingSettingsResponse>("/admin/pleading-settings", { token });
}

export async function savePleadingSettings(settings: PleadingSettings, token: string): Promise<PleadingSettingsResponse> {
  return apiRequest<PleadingSettingsResponse>("/admin/pleading-settings", { method: "PUT", body: settings, token });
}

export async function listTemplates(token: string): Promise<DocumentTemplateListResponse> {
  return apiRequest<DocumentTemplateListResponse>("/admin/templates", { token });
}

export async function uploadTemplate(name: string, file: File, token: string): Promise<DocumentTemplateInfo> {
  const form = new FormData();
  form.append("name", name);
  form.append("file", file);
  return apiRequestFormData<DocumentTemplateInfo>("/admin/templates", form, { token });
}

export async function downloadTemplate(templateId: number, token: string): Promise<Blob> {
  return apiRequestBlob(`/admin/templates/${templateId}/download`, { token });
}

export async function deleteTemplate(templateId: number, token: string): Promise<void> {
  await apiRequest(`/admin/templates/${templateId}`, { method: "DELETE", token });
}
