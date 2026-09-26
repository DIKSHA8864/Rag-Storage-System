"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import { askStream } from "@/lib/api/endUserAuth";
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

interface AskResult {
  query: string;
  answer: string;
  sources: EndUserQuerySource[];
  isComplete: boolean;
}

function AskContent() {
  const { endUserToken, logout } = useEndUserAuth();
  const router = useRouter();

  const [result, setResult] = useState<AskResult | null>(null);
  const [isAsking, setIsAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleAsk(query: string) {
    if (!endUserToken) return;

    setError(null);
    setIsAsking(true);
    setResult({ query, answer: "", sources: [], isComplete: false });

    let streamError: string | null = null;

    try {
      await askStream(query, endUserToken, {
        onSources: (sources) => setResult((prev) => (prev ? { ...prev, sources } : prev)),
        onAnswerChunk: (text) => setResult((prev) => (prev ? { ...prev, answer: prev.answer + text } : prev)),
        onError: (detail) => {
          streamError = detail;
        },
      });

      if (streamError) {
        // A failure is shown as a failure - never as an empty "no supporting material" answer.
        setResult(null);
        setError(streamError);
      } else {
        setResult((prev) => (prev ? { ...prev, isComplete: true } : prev));
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        router.push("/portal/login");
        return;
      }
      setResult(null);
      setError(err instanceof ApiError ? err.message : "Could not get an answer. Please try again.");
    } finally {
      setIsAsking(false);
    }
  }

  return (
    <div className="p-page">
      <h1>Ask a question</h1>
      <p className="p-lede">
        Answers come only from the firm&apos;s legal library, with the sources they&apos;re based on. If the library
        doesn&apos;t cover your question, you&apos;ll be told so instead of getting a guess.
      </p>

      <div className="p-card">
        <ResearchQueryForm onSubmit={handleAsk} isLoading={isAsking} clearOnSubmit label="Your question" />
        {!result && !isAsking && (
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

      {error && (
        <div style={{ marginTop: "1rem" }}>
          <ErrorMessage message={error} />
        </div>
      )}

      {result && (
        <div className="p-card" style={{ marginTop: "1.25rem" }}>
          <p className="p-question">{result.query}</p>
          {result.answer === "" && !result.isComplete ? (
            <p className="p-muted">Searching the library...</p>
          ) : (
            <AnswerPanel answer={result.answer} hasSupport={result.sources.length > 0} sources={result.sources} />
          )}
          {result.isComplete && <SourcesPanel sources={result.sources} />}
        </div>
      )}
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
