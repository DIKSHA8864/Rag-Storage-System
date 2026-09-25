"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/lib/auth/useAuth";
import {
  askResearchStream,
  deleteResearchThread,
  exportResearchThread,
  getResearchThread,
  listResearchThreads,
  renameResearchThread,
} from "@/lib/api/research";
import type { OwnerResearchSource, ResearchThreadInfo } from "@/lib/api/types";
import { ApiError } from "@/lib/api/client";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { ResearchQueryForm } from "@/components/research/ResearchQueryForm";
import { AnswerPanel } from "@/components/research/AnswerPanel";
import { SourcesPanel } from "@/components/research/SourcesPanel";

interface Turn {
  key: string;
  question: string;
  answer: string;
  sources: OwnerResearchSource[];
  isStreaming: boolean;
  error: string | null;
}

/**
 * The Owner Research Console: saved research threads (left) and the
 * selected thread's questions and answers (right). Answers stream in
 * from POST /research/ask/stream - the same retrieval + citation-locked
 * generation as every other research path - and each completed answer
 * is saved to its thread with its locked sources, so the thread (or any
 * single answer) exports as a memo exactly as shown here.
 */
export default function ResearchPage() {
  const { token, logout } = useAuth();

  const [threads, setThreads] = useState<ResearchThreadInfo[]>([]);
  const [activeThread, setActiveThread] = useState<ResearchThreadInfo | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [isAsking, setIsAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  const turnCounter = useRef(0);
  const conversationEndRef = useRef<HTMLDivElement>(null);

  const fail = useCallback(
    (err: unknown, fallback: string) => {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(err instanceof ApiError ? err.message : fallback);
    },
    [logout]
  );

  const refreshThreads = useCallback(async () => {
    if (!token) return;
    try {
      setThreads(await listResearchThreads(token));
    } catch (err) {
      fail(err, "Could not load your research threads.");
    }
  }, [token, fail]);

  useEffect(() => {
    void refreshThreads();
  }, [refreshThreads]);

  useEffect(() => {
    conversationEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length]);

  async function openThread(thread: ResearchThreadInfo) {
    if (!token || isAsking) return;
    setError(null);
    try {
      const detail = await getResearchThread(thread.id, token);
      const loaded: Turn[] = [];
      let question: string | null = null;
      for (const message of detail.messages) {
        if (message.role === "user") question = message.content;
        else if (question !== null) {
          loaded.push({
            key: `saved-${message.id}`,
            question,
            answer: message.content,
            sources: message.sources,
            isStreaming: false,
            error: null,
          });
          question = null;
        }
      }
      setActiveThread(detail.thread);
      setTurns(loaded);
    } catch (err) {
      fail(err, "Could not open that thread.");
    }
  }

  function startNewThread() {
    if (isAsking) return;
    setActiveThread(null);
    setTurns([]);
    setError(null);
  }

  function updateTurn(key: string, change: (turn: Turn) => Turn) {
    setTurns((prev) => prev.map((turn) => (turn.key === key ? change(turn) : turn)));
  }

  async function handleAsk(query: string) {
    if (!token) return;
    setError(null);
    setIsAsking(true);
    turnCounter.current += 1;
    const key = `live-${turnCounter.current}`;
    setTurns((prev) => [...prev, { key, question: query, answer: "", sources: [], isStreaming: true, error: null }]);

    try {
      await askResearchStream({ query, thread_id: activeThread?.id }, token, {
        onThread: ({ thread_id, title }) =>
          setActiveThread((prev) =>
            prev && prev.id === thread_id
              ? prev
              : { id: thread_id, title, created_at: "", updated_at: "", message_count: 0 }
          ),
        onSources: (sources) => updateTurn(key, (turn) => ({ ...turn, sources })),
        onAnswerChunk: (text) => updateTurn(key, (turn) => ({ ...turn, answer: turn.answer + text })),
        onError: (detail) => updateTurn(key, (turn) => ({ ...turn, error: detail })),
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      updateTurn(key, (turn) => ({
        ...turn,
        error: err instanceof ApiError ? err.message : "Something went wrong. Please try again.",
      }));
    } finally {
      updateTurn(key, (turn) => ({ ...turn, isStreaming: false }));
      setIsAsking(false);
      void refreshThreads();
    }
  }

  async function handleRename() {
    if (!token || !activeThread) return;
    const title = window.prompt("Rename this research thread", activeThread.title)?.trim();
    if (!title || title === activeThread.title) return;
    try {
      setActiveThread(await renameResearchThread(activeThread.id, title, token));
      void refreshThreads();
    } catch (err) {
      fail(err, "Could not rename the thread.");
    }
  }

  async function handleDelete() {
    if (!token || !activeThread) return;
    if (!window.confirm(`Delete "${activeThread.title}" and all its answers? This can't be undone.`)) return;
    try {
      await deleteResearchThread(activeThread.id, token);
      startNewThread();
      void refreshThreads();
    } catch (err) {
      fail(err, "Could not delete the thread.");
    }
  }

  async function handleExport(format: "docx" | "pdf") {
    if (!token || !activeThread) return;
    setIsExporting(true);
    setError(null);
    try {
      downloadBlob(await exportResearchThread(activeThread.id, format, token), `research-memo-${activeThread.id}.${format}`);
    } catch (err) {
      fail(err, "Export failed. Please try again.");
    } finally {
      setIsExporting(false);
    }
  }

  const hasSavedAnswers = turns.some((turn) => !turn.isStreaming && !turn.error && turn.answer !== "");

  return (
    <div style={{ display: "flex", gap: "1.5rem", alignItems: "flex-start", maxWidth: 1150, margin: "0 auto", flexWrap: "wrap" }}>
      <aside style={{ flex: "0 0 240px", minWidth: 200 }}>
        <button type="button" onClick={startNewThread} disabled={isAsking} style={{ width: "100%", marginBottom: "0.75rem" }}>
          + New research
        </button>
        <h2 style={{ fontSize: "0.85rem", color: "#777", textTransform: "uppercase", letterSpacing: "0.04em" }}>
          Your threads
        </h2>
        {threads.length === 0 ? (
          <p style={{ fontSize: "0.85rem", color: "#888" }}>Your questions are saved here automatically.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            {threads.map((thread) => {
              const isActive = activeThread?.id === thread.id;
              return (
                <li key={thread.id}>
                  <button
                    type="button"
                    onClick={() => openThread(thread)}
                    disabled={isAsking}
                    aria-current={isActive ? "true" : undefined}
                    style={{
                      width: "100%",
                      textAlign: "left",
                      padding: "0.4rem 0.5rem",
                      border: "1px solid",
                      borderColor: isActive ? "#1a5fb4" : "#e5e5e5",
                      background: isActive ? "#eaf1fb" : "#fff",
                      borderRadius: 4,
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ fontSize: "0.85rem", fontWeight: isActive ? 600 : 400 }}>{thread.title}</div>
                    <div style={{ fontSize: "0.75rem", color: "#888" }}>
                      {Math.floor(thread.message_count / 2)} answer{thread.message_count === 2 ? "" : "s"} -{" "}
                      {new Date(thread.updated_at).toLocaleDateString()}
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </aside>

      <main style={{ flex: "1 1 520px", minWidth: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: "1rem", flexWrap: "wrap" }}>
          <h1 style={{ margin: 0 }}>{activeThread ? activeThread.title : "Research Console"}</h1>
          {activeThread && (
            <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
              <button type="button" onClick={handleRename} disabled={isAsking}>Rename</button>
              <button type="button" onClick={() => handleExport("docx")} disabled={isExporting || isAsking || !hasSavedAnswers}>
                Export memo (DOCX)
              </button>
              <button type="button" onClick={() => handleExport("pdf")} disabled={isExporting || isAsking || !hasSavedAnswers}>
                Export memo (PDF)
              </button>
              <button type="button" onClick={handleDelete} disabled={isAsking}>Delete</button>
            </div>
          )}
        </div>
        <p style={{ color: "#666" }}>
          Answers come only from the firm&apos;s library, each with the passages it relies on. If the library
          doesn&apos;t cover a point, you&apos;re told so instead of getting a guess.
        </p>

        {error && <ErrorMessage message={error} />}

        <div style={{ display: "flex", flexDirection: "column", gap: "1.75rem", margin: "1rem 0" }}>
          {turns.map((turn, index) => (
            <section key={turn.key} aria-label={`Question ${index + 1}`}>
              <p style={{ fontWeight: 600, margin: "0 0 0.5rem 0" }}>{turn.question}</p>
              {turn.error ? (
                <ErrorMessage message={turn.error} />
              ) : turn.answer === "" && turn.isStreaming ? (
                <p style={{ color: "#777" }}>Searching the library...</p>
              ) : (
                <>
                  <AnswerPanel answer={turn.answer} hasSupport={turn.sources.length > 0} sources={turn.sources} scope={turn.key} />
                  {!turn.isStreaming && <SourcesPanel sources={turn.sources} scope={turn.key} />}
                </>
              )}
            </section>
          ))}
          <div ref={conversationEndRef} />
        </div>

        <ResearchQueryForm
          onSubmit={handleAsk}
          isLoading={isAsking}
          clearOnSubmit
          label={turns.length > 0 ? "Follow-up question" : "Research question"}
        />
      </main>
    </div>
  );
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
