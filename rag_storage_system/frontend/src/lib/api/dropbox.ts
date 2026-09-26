import { apiRequest } from "./client";

// The owner's own Dropbox connection for vault sync (app/api/dropbox_api.py).

export interface DropboxFolderChoice {
  path: string;
  library_folder: string;
}

export interface DropboxStatus {
  available: boolean;
  redirect_uri: string;
  connected: boolean;
  needs_reconnect: boolean;
  account_name: string | null;
  account_email: string | null;
  connected_by: string | null;
  connected_at: string | null;
  folders: DropboxFolderChoice[];
}

export interface DropboxFolderEntry {
  name: string;
  path: string;
  selected: boolean;
}

export interface DropboxFolderList {
  path: string;
  parent: string | null;
  folders: DropboxFolderEntry[];
}

export async function getDropboxStatus(token: string): Promise<DropboxStatus> {
  return apiRequest<DropboxStatus>("/admin/dropbox", { token });
}

export async function startDropboxConnect(token: string): Promise<{ authorize_url: string }> {
  return apiRequest("/admin/dropbox/connect", { method: "POST", token });
}

export async function completeDropboxConnect(code: string, state: string, token: string): Promise<DropboxStatus> {
  return apiRequest<DropboxStatus>("/admin/dropbox/connect/complete", { method: "POST", body: { code, state }, token });
}

export async function listDropboxFolders(path: string, token: string): Promise<DropboxFolderList> {
  return apiRequest<DropboxFolderList>(`/admin/dropbox/folders?path=${encodeURIComponent(path)}`, { token });
}

export async function saveDropboxFolders(paths: string[], token: string): Promise<DropboxStatus> {
  return apiRequest<DropboxStatus>("/admin/dropbox/folders", { method: "PUT", body: { paths }, token });
}

export async function disconnectDropbox(token: string): Promise<DropboxStatus> {
  return apiRequest<DropboxStatus>("/admin/dropbox", { method: "DELETE", token });
}
