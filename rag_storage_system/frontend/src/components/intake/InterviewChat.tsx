"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { resumeInterview, sendInterviewMessage, startInterview } from "@/lib/api/intake";
import type { InterviewStateInfo } from "@/lib/api/types";
import { ApiError } from "@/lib/api/client";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ReportPanel } from "./ReportPanel";
import { UploadPanel } from "./UploadPanel";

interface InterviewChatProps {
  sessionId: number;
  endUserToken: string;
  onStartOver: () => void;
  onUnauthorized: () => void;
}

interface ChatMessage {
  id: number | string;
  role: string;
  content: string;
}

// The 6 real stages app/intake_engine/models.py's InterviewState
// defines - shown here only as progress labels, never as a frontend-
// invented flow. The actual prompts/questions always come from the
// backend's own `prompt`/`reply` text.
const STAGE_ORDER = [
  "language_selection",
  "terms_acceptance",
  "mandatory_sweep",
  "protected_activity",
  "general_narrative",
  "complete",
];

const STAGE_LABELS: Record<string, { en: string; es: string }> = {
  language_selection: { en: "Language", es: "Idioma" },
  terms_acceptance: { en: "Terms", es: "Terminos" },
  mandatory_sweep: { en: "Screening questions", es: "Preguntas de deteccion" },
  protected_activity: { en: "Protected activity", es: "Actividad protegida" },
  general_narrative: { en: "Your story", es: "Su historia" },
  complete: { en: "Complete", es: "Completo" },
};

const LANGUAGE_QUICK_REPLIES = [
  { label: "English", value: "english" },
  { label: "Espanol", value: "espanol" },
];

// Every screening / protected-activity question is a yes-or-no question
// (app/intake_engine/mandatory_sweep.py, protected_activity.py) - one tap
// answers it; the text box stays available for anything more to add.
function yesNoQuickReplies(language: string | null): { label: string; value: string }[] {
  return language === "es"
    ? [
        { label: "Si", value: "Si" },
        { label: "No", value: "No" },
        { label: "No estoy seguro/a", value: "No estoy seguro/a" },
      ]
    : [
        { label: "Yes", value: "Yes" },
        { label: "No", value: "No" },
        { label: "Not sure", value: "Not sure" },
      ];
}

function termsQuickReply(language: string | null): { label: string; value: string } {
  return language === "es" ? { label: "Acepto", value: "acepto" } : { label: "I agree", value: "i agree" };
}

/**
 * The real, adaptive Client Interview - every question/prompt shown
 * here is exactly what app/intake_engine/engine.py's submit_message()
 * returned; this component never generates, alters, or hardcodes a
 * question. Language selection and terms acceptance are simply the
 * first two turns of this same conversation - not a separate flow.
 */
export function InterviewChat({ sessionId, endUserToken, onStartOver, onUnauthorized }: InterviewChatProps) {
  const [state, setState] = useState<InterviewStateInfo | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [draft, setDraft] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [lastTurnRejected, setLastTurnRejected] = useState(false);

  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const messageIdCounter = useRef(0);
  const loadInterview = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);

    try {
      const resumed = await resumeInterview(sessionId, endUserToken);
      setState(resumed.state);
      setMessages(resumed.messages.map((m) => ({ id: m.id, role: m.role, content: m.content })));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onUnauthorized();
        return;
      }
      if (err instanceof ApiError && err.status === 404) {
        try {
          const started = await startInterview(sessionId, endUserToken);
          setState(started.state);
          setMessages([{ id: "opening", role: "assistant", content: started.prompt }]);
        } catch (startErr) {
          setLoadError(
            startErr instanceof ApiError ? startErr.message : "Could not start your interview. Please try again."
          );
        }
      } else {
        setLoadError(err instanceof ApiError ? err.message : "Could not load your interview. Please try again.");
      }
    } finally {
      setIsLoading(false);
    }
  }, [sessionId, endUserToken, onUnauthorized]);

  useEffect(() => {
    // Fetching on mount is exactly what this effect is for - same
    // legitimate case as every other page-load fetch in this app.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadInterview();
  }, [loadInterview]);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend(rawMessage: string) {
    const message = rawMessage.trim();
    if (message === "" || isSending) return;

    setSendError(null);
    setIsSending(true);
    setLastTurnRejected(false);

    // Optimistic: the backend records the user's turn unconditionally,
    // so showing it immediately matches what will actually be
    // persisted either way. A ref-based counter (not Date.now()) keeps
    // this deterministic rather than calling an impure function.
    messageIdCounter.current += 1;
    const optimisticId = `pending-${messageIdCounter.current}`;
    setMessages((prev) => [...prev, { id: optimisticId, role: "user", content: message }]);
    setDraft("");

    try {
      const result = await sendInterviewMessage(sessionId, message, endUserToken);
      setState(result.state);
      setMessages((prev) => [...prev, { id: `${optimisticId}-reply`, role: "assistant", content: result.reply }]);
      setLastTurnRejected(result.error);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onUnauthorized();
        return;
      }
      setSendError(err instanceof ApiError ? err.message : "Could not send your answer. Please try again.");
      setMessages((prev) => prev.filter((m) => m.id !== optimisticId));
    } finally {
      setIsSending(false);
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    handleSend(draft);
  }

  if (isLoading) {
    return <LoadingSpinner label="Loading your interview... / Cargando su entrevista..." />;
  }

  if (loadError || !state) {
    return (
      <div style={{ maxWidth: 560, margin: "3rem auto", padding: "0 1rem" }}>
        <ErrorMessage message={loadError ?? "Something went wrong."} />
        <button type="button" onClick={loadInterview} style={{ marginTop: "1rem" }}>
          Retry / Reintentar
        </button>
      </div>
    );
  }

  const isComplete = state.current_state === "complete";
  const stageIndex = STAGE_ORDER.indexOf(state.current_state);
  // Evidence can only be attached once the client has accepted the terms.
  const canUpload = stageIndex > STAGE_ORDER.indexOf("terms_acceptance");
  const uploadPanel = canUpload ? (
    <UploadPanel
      sessionId={sessionId}
      endUserToken={endUserToken}
      language={state.language}
      onUnauthorized={onUnauthorized}
    />
  ) : null;

  return (
    <div style={{ maxWidth: 560, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <h1 style={{ fontSize: "1.25rem" }}>Client Intake</h1>
        <button type="button" onClick={onStartOver} style={{ fontSize: "0.8rem" }}>
          New intake / Nueva admision
        </button>
      </div>

      <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap", margin: "0.75rem 0 1rem 0" }}>
        {STAGE_ORDER.map((stage, index) => {
          const label = STAGE_LABELS[stage][state.language === "es" ? "es" : "en"];
          const isCurrent = index === stageIndex;
          const isPast = stageIndex >= 0 && index < stageIndex;
          return (
            <span
              key={stage}
              style={{
                fontSize: "0.75rem",
                fontWeight: isCurrent ? 700 : 400,
                padding: "0.2rem 0.5rem",
                borderRadius: 4,
                background: isCurrent ? "#eaf1fb" : isPast ? "#e8f5e9" : "#f0f0f0",
                color: isCurrent ? "#1a5fb4" : isPast ? "#2e7d32" : "#777",
              }}
            >
              {label}
            </span>
          );
        })}
      </div>

      {state.question_number !== null && (
        <div style={{ margin: "0 0 0.75rem 0" }}>
          <p style={{ fontSize: "0.85rem", color: "#555", margin: "0 0 0.3rem 0" }}>
            {state.language === "es"
              ? `Pregunta ${state.question_number} de ${state.total_questions}`
              : `Question ${state.question_number} of ${state.total_questions}`}
            {state.question_number === 1 &&
              (state.language === "es"
                ? " - preguntas cortas, casi todas de si o no (unos 5 minutos)."
                : " - short questions, mostly yes or no (about 5 minutes).")}
            {state.question_number === state.total_questions &&
              (state.language === "es" ? " - la ultima pregunta." : " - the last question.")}
          </p>
          <div style={{ height: 6, background: "#eee", borderRadius: 3 }}>
            <div
              style={{
                width: `${Math.round(((state.question_number - 1) / state.total_questions) * 100)}%`,
                height: "100%",
                background: "#1a5fb4",
                borderRadius: 3,
              }}
            />
          </div>
        </div>
      )}

      <div
        style={{
          border: "1px solid #e5e5e5",
          borderRadius: 6,
          padding: "1rem",
          minHeight: 240,
          maxHeight: 420,
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: "0.6rem",
        }}
      >
        {messages.map((message) => (
          <div
            key={message.id}
            style={{
              alignSelf: message.role === "user" ? "flex-end" : "flex-start",
              maxWidth: "80%",
              padding: "0.5rem 0.75rem",
              borderRadius: 8,
              background: message.role === "user" ? "#1a5fb4" : "#f0f0f0",
              color: message.role === "user" ? "#fff" : "#1a1a1a",
              whiteSpace: "pre-wrap",
            }}
          >
            {message.content}
          </div>
        ))}
        <div ref={transcriptEndRef} />
      </div>

      {lastTurnRejected && (
        <p style={{ fontSize: "0.8rem", color: "#8a6116", marginTop: "0.5rem" }}>
          {state.language === "es"
            ? "No se entendio esa respuesta - por favor intente de nuevo."
            : "That answer wasn't recognized - please try again."}
        </p>
      )}

      {sendError && <ErrorMessage message={sendError} />}

            {isComplete ? (
        <>
          <p style={{ marginTop: "1rem", color: "#2e7d32", fontWeight: 600 }}>
            {state.language === "es" ? "Su entrevista ha finalizado. Gracias." : "Your interview is complete. Thank you."}
          </p>
          {uploadPanel}
          <ReportPanel sessionId={sessionId} endUserToken={endUserToken} language={state.language} />
        </>
      ) : (
        <div style={{ marginTop: "1rem" }}>
          {state.current_state === "language_selection" && (
            <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.5rem" }}>
              {LANGUAGE_QUICK_REPLIES.map((option) => (
                <button key={option.value} type="button" onClick={() => handleSend(option.value)} disabled={isSending}>
                  {option.label}
                </button>
              ))}
            </div>
          )}

          {state.current_state === "terms_acceptance" && (
            <div style={{ marginBottom: "0.5rem" }}>
              <button type="button" onClick={() => handleSend(termsQuickReply(state.language).value)} disabled={isSending}>
                {termsQuickReply(state.language).label}
              </button>
            </div>
          )}

          {(state.current_state === "mandatory_sweep" || state.current_state === "protected_activity") && (
            <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.5rem", flexWrap: "wrap" }}>
              {yesNoQuickReplies(state.language).map((option) => (
                <button key={option.value} type="button" onClick={() => handleSend(option.value)} disabled={isSending}>
                  {option.label}
                </button>
              ))}
            </div>
          )}

          <form onSubmit={handleSubmit} style={{ display: "flex", gap: "0.5rem", alignItems: "flex-end" }}>
            {state.current_state === "general_narrative" ? (
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                disabled={isSending}
                rows={6}
                placeholder={
                  state.language === "es"
                    ? "Cuente lo que paso, con sus propias palabras..."
                    : "Tell us what happened, in your own words..."
                }
                style={{ flex: 1, resize: "vertical" }}
              />
            ) : (
              <input
                type="text"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                disabled={isSending}
                placeholder={
                  state.current_state === "mandatory_sweep" || state.current_state === "protected_activity"
                    ? state.language === "es"
                      ? "O escriba mas detalles..."
                      : "Or type more detail..."
                    : state.language === "es"
                      ? "Escriba su respuesta..."
                      : "Type your answer..."
                }
                style={{ flex: 1 }}
              />
            )}
            <button type="submit" disabled={isSending || draft.trim() === ""} aria-busy={isSending}>
              {isSending ? "..." : state.language === "es" ? "Enviar" : "Send"}
            </button>
          </form>
          {uploadPanel}
        </div>
      )}
    </div>
  );
}