"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  askStream,
  createEndUserThread,
  getEndUserThreadMessages,
  listEndUserThreads,
  type EndUserThreadInfo,
} from "@/lib/api/endUserAuth";
import type { EndUserQuerySource } from "@/lib/api/types";
import { useEndUserAuth } from "@/lib/clientAuth/useEndUserAuth";
import { RequireEndUser } from "@/components/portal/RequireEndUser";
import { AnswerPanel } from "@/components/research/AnswerPanel";
import { ResearchQueryForm } from "@/components/research/ResearchQueryForm";
import { SourcesPanel } from "@/components/research/SourcesPanel";
import { ErrorMessage } from "@/components/ui/ErrorMessage";

const EXAMPLE_QUESTIONS = [
  "Is my employer required to pay overtime after 8 hours in a day?",
  "Am I entitled to meal and rest breaks?",
  "Can I be fired for complaining about harassment?",
];

const TITLE_LENGTH = 80;

interface Turn {
  key: string;
  question: string;
  answer: string;
  sources: EndUserQuerySource[];
  isStreaming: boolean;
  error: string | null;
}

function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const today = new Date();
  return date.toDateString() === today.toDateString()
    ? `Today, ${date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`
    : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function AskContent() {
  const { endUserToken, logout } = useEndUserAuth();
  const router = useRouter();

  const [threads, setThreads] = useState<EndUserThreadInfo[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [activeThread, setActiveThread] = useState<EndUserThreadInfo | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [isAsking, setIsAsking] = useState(false);
  const [isOpening, setIsOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const conversationEndRef = useRef<HTMLDivElement>(null);

  const handleUnauthorized = useCallback(() => {
    logout();
    router.push("/portal/login");
  }, [logout, router]);

  const loadThreads = useCallback(async () => {
    if (!endUserToken) return;
    try {
      setThreads((await listEndUserThreads(endUserToken)).threads);
      setHistoryError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        handleUnauthorized();
        return;
      }
      setHistoryError("Your earlier questions couldn't be loaded.");
    }
  }, [endUserToken, handleUnauthorized]);

  useEffect(() => {
    loadThreads();
  }, [loadThreads]);

  useEffect(() => {
    if (turns.length > 0) conversationEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [turns.length]);

  function updateTurn(key: string, change: (turn: Turn) => Turn) {
    setTurns((current) => current.map((turn) => (turn.key === key ? change(turn) : turn)));
  }

  async function handleAsk(query: string) {
    if (!endUserToken || isAsking) return;
    setError(null);
    setIsAsking(true);

    const key = `new-${Date.now()}`;
    setTurns((current) => [...current, { key, question: query, answer: "", sources: [], isStreaming: true, error: null }]);

    try {
      // The first question starts a saved conversation, named after that question.
      let thread = activeThread;
      if (!thread) {
        const title = query.length > TITLE_LENGTH ? `${query.slice(0, TITLE_LENGTH - 1)}…` : query;
        thread = await createEndUserThread(title, endUserToken);
        setActiveThread(thread);
      }

      let streamError: string | null = null;
      await askStream(
        query,
        endUserToken,
        {
          onSources: (sources) => updateTurn(key, (turn) => ({ ...turn, sources })),
          onAnswerChunk: (text) => updateTurn(key, (turn) => ({ ...turn, answer: turn.answer + text })),
          onError: (detail) => {
            streamError = detail;
          },
        },
        thread.id
      );
      // A failure is shown as a failure - never as an empty "no supporting material" answer.
      updateTurn(key, (turn) => ({ ...turn, isStreaming: false, error: streamError }));
      loadThreads();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        handleUnauthorized();
        return;
      }
      updateTurn(key, (turn) => ({
        ...turn,
        isStreaming: false,
        error: err instanceof ApiError ? err.message : "Could not get an answer. Please try again.",
      }));
    } finally {
      setIsAsking(false);
    }
  }

  async function openThread(thread: EndUserThreadInfo) {
    if (!endUserToken || isAsking) return;
    setError(null);
    setIsOpening(true);
    try {
      const { messages } = await getEndUserThreadMessages(thread.id, endUserToken);
      const loaded: Turn[] = [];
      for (const message of messages) {
        if (message.role === "user") {
          loaded.push({ key: `m-${message.id}`, question: message.content, answer: "", sources: [], isStreaming: false, error: null });
        } else if (loaded.length > 0) {
          const last = loaded[loaded.length - 1];
          loaded[loaded.length - 1] = { ...last, answer: message.content, sources: message.sources ?? [] };
        }
      }
      setActiveThread(thread);
      setTurns(loaded);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        handleUnauthorized();
        return;
      }
      setError("That conversation couldn't be opened. Please try again.");
    } finally {
      setIsOpening(false);
    }
  }

  function startNew() {
    if (isAsking) return;
    setActiveThread(null);
    setTurns([]);
    setError(null);
  }

  return (
    <div className="p-page p-ask" style={{ maxWidth: 1040 }}>
      <aside className="p-history" aria-label="Your earlier questions">
        <button type="button" className="p-primary" onClick={startNew} disabled={isAsking} style={{ width: "100%" }}>
          + New question
        </button>
        <h2 className="p-history-title">Your questions</h2>
        {historyError && <p className="p-note is-warn">{historyError}</p>}
        {threads.length === 0 && !historyError ? (
          <p className="p-muted" style={{ fontSize: "0.85rem", margin: 0 }}>
            Questions you ask are saved here, so you can come back to them.
          </p>
        ) : (
          <ul>
            {threads.map((thread) => {
              const isActive = activeThread?.id === thread.id;
              return (
                <li key={thread.id}>
                  <button
                    type="button"
                    onClick={() => openThread(thread)}
                    disabled={isAsking || isOpening}
                    aria-current={isActive ? "true" : undefined}
                    className={isActive ? "is-active" : undefined}
                  >
                    <span>{thread.title}</span>
                    <small>{formatWhen(thread.updated_at)}</small>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </aside>

      <div className="p-ask-main">
        <h1>{activeThread ? activeThread.title : "Ask a question"}</h1>
        {!activeThread && (
          <p className="p-lede">
            Answers come only from the firm&apos;s legal library, with the sources they&apos;re based on. If the library
            doesn&apos;t cover your question, you&apos;ll be told so instead of getting a guess.
          </p>
        )}

        {error && (
          <div style={{ margin: "0.75rem 0" }}>
            <ErrorMessage message={error} />
          </div>
        )}

        {turns.map((turn) => (
          <section key={turn.key} className="p-card" style={{ marginBottom: "1rem" }} aria-label={turn.question}>
            <p className="p-question">{turn.question}</p>
            {turn.error ? (
              <ErrorMessage message={turn.error} />
            ) : turn.answer === "" && turn.isStreaming ? (
              <p className="p-muted">Searching the library...</p>
            ) : (
              <>
                <AnswerPanel answer={turn.answer} hasSupport={turn.sources.length > 0} sources={turn.sources} scope={turn.key} />
                {!turn.isStreaming && <SourcesPanel sources={turn.sources} scope={turn.key} />}
              </>
            )}
          </section>
        ))}
        <div ref={conversationEndRef} />

        <div className="p-card">
          <ResearchQueryForm
            onSubmit={handleAsk}
            isLoading={isAsking}
            clearOnSubmit
            label={turns.length > 0 ? "Ask a follow-up question" : "Your question"}
          />
          {turns.length === 0 && !isAsking && (
            <div>
              <p className="p-muted" style={{ fontSize: "0.85rem", margin: "1.25rem 0 0" }}>
                Not sure where to start? Try one of these:
              </p>
              <div className="p-examples">
                {EXAMPLE_QUESTIONS.map((example) => (
                  <button key={example} type="button" onClick={() => handleAsk(example)}>
                    {example}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function AskPage() {
  return (
    <RequireEndUser>
      <AskContent />
    </RequireEndUser>
  );
}
