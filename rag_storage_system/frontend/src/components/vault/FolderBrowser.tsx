"use client";

import { useState, type FormEvent } from "react";

import type { CategoryInfo } from "@/lib/api/types";

interface FolderBrowserProps {
  categories: CategoryInfo[];
  currentPath: string;
  onNavigate: (path: string) => void;
  onCreateFolder: (name: string) => Promise<void>;
  isCreatingFolder: boolean;
  createFolderError: string | null;
}

/**
 * Breadcrumb + child-folder list, built entirely from the flat
 * "Parent/Child" category strings GET /categories returns (see
 * app/api/schemas.py's CategoryCreateRequest) - there is no separate
 * tree endpoint, so nesting is derived client-side from those names.
 */
export function FolderBrowser({
  categories,
  currentPath,
  onNavigate,
  onCreateFolder,
  isCreatingFolder,
  createFolderError,
}: FolderBrowserProps) {
  const [newFolderName, setNewFolderName] = useState("");

  const childFolders = categories.filter((category) => {
    if (currentPath === "") {
      return !category.name.includes("/");
    }
    const prefix = `${currentPath}/`;
    return category.name.startsWith(prefix) && !category.name.slice(prefix.length).includes("/");
  });

  const breadcrumbSegments = currentPath === "" ? [] : currentPath.split("/");

  async function handleCreateFolder(event: FormEvent) {
    event.preventDefault();
    const trimmed = newFolderName.trim();
    if (trimmed === "") return;

    await onCreateFolder(trimmed);
    setNewFolderName("");
  }

  return (
    <div>
      <nav aria-label="Folder path" style={{ fontSize: "0.9rem", marginBottom: "0.75rem" }}>
        <button type="button" onClick={() => onNavigate("")} style={{ fontWeight: currentPath === "" ? 700 : 400 }}>
          Vault
        </button>
        {breadcrumbSegments.map((segment, index) => {
          const path = breadcrumbSegments.slice(0, index + 1).join("/");
          return (
            <span key={path}>
              {" / "}
              <button
                type="button"
                onClick={() => onNavigate(path)}
                style={{ fontWeight: path === currentPath ? 700 : 400 }}
              >
                {segment}
              </button>
            </span>
          );
        })}
      </nav>

      {childFolders.length > 0 && (
        <ul style={{ listStyle: "none", margin: "0 0 1rem 0", padding: 0, display: "flex", flexDirection: "column", gap: "0.4rem" }}>
          {childFolders.map((folder) => (
            <li key={folder.name}>
              <button
                type="button"
                onClick={() => onNavigate(folder.name)}
                style={{ display: "flex", justifyContent: "space-between", width: "100%", textAlign: "left", padding: "0.4rem 0.6rem" }}
              >
                <span>📁 {folder.name.split("/").pop()}</span>
                <span style={{ color: "#777" }}>
                  {folder.document_count} document{folder.document_count === 1 ? "" : "s"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={handleCreateFolder} style={{ display: "flex", gap: "0.5rem" }}>
        <input
          type="text"
          value={newFolderName}
          onChange={(e) => setNewFolderName(e.target.value)}
          placeholder={currentPath === "" ? "New top-level folder name" : `New folder inside ${currentPath}`}
          disabled={isCreatingFolder}
          style={{ flex: 1 }}
        />
        <button type="submit" disabled={isCreatingFolder || newFolderName.trim() === ""}>
          {isCreatingFolder ? "Creating..." : "Create folder"}
        </button>
      </form>

      {createFolderError && <p style={{ color: "#c0392b", fontSize: "0.85rem" }}>{createFolderError}</p>}
    </div>
  );
}