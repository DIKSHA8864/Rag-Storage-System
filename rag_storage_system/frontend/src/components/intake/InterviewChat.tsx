"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { resumeInterview, sendInterviewMessage, startInterview } from "@/lib/api/intake";
import type { InterviewStateInfo } from "@/lib/api/types";
import { ApiError } from "@/lib/api/client";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ReportPanel } from "./ReportPanel";
import { TalkToPerson } from "./TalkToPerson";
import { UploadPanel } from "./UploadPanel";
import { VoiceInterviewer } from "./VoiceInterviewer";

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

// The real stages app/intake_engine/models.py's InterviewState defines,
// in the order the backend runs them for this interview's flow - shown
// here only as progress labels, never as a frontend-invented flow. The
// actual prompts/questions always come from the backend's own
// `prompt`/`reply` text.
const STAGE_ORDER_BY_FLOW: Record<number, string[]> = {
  1: ["language_selection", "terms_acceptance", "mandatory_sweep", "protected_activity", "general_narrative", "complete"],
  2: [
    "language_selection",
    "terms_acceptance",
    "story",
    "follow_up",
    "mandatory_sweep",
    "protected_activity",
    "timeline",
    "documents",
    "complete",
  ],
};

const STAGE_LABELS: Record<string, { en: string; es: string }> = {
  language_selection: { en: "Language", es: "Idioma" },
  terms_acceptance: { en: "Terms", es: "Terminos" },
  story: { en: "Your story", es: "Su historia" },
  follow_up: { en: "Follow-up", es: "Seguimiento" },
  mandatory_sweep: { en: "Screening questions", es: "Preguntas de deteccion" },
  protected_activity: { en: "Protected activity", es: "Actividad protegida" },
  timeline: { en: "Key dates", es: "Fechas" },
  documents: { en: "Documents", es: "Documentos" },
  general_narrative: { en: "Your story", es: "Su historia" },
  complete: { en: "Complete", es: "Completo" },
};

type QuickReply = { label: string; value: string };

// Answers the backend understands for each key-date question
// (app/intake_engine/timeline.py) - besides typing a date.
function timelineQuickReplies(questionKey: string | null, language: string | null): QuickReply[] {
  const es = language === "es";
  const replies: QuickReply[] = [es ? { label: "No se", value: "no se" } : { label: "Don't know", value: "don't know" }];
  if (questionKey === "date_first_complaint") {
    replies.push(es ? { label: "Nunca me queje", value: "nunca" } : { label: "Never complained", value: "none" });
  }
  if (questionKey === "date_last_day") {
    replies.push(
      es ? { label: "Sigo trabajando alli", value: "sigo trabajando" } : { label: "I still work there", value: "still working" }
    );
  }
  return replies;
}

const LANGUAGE_QUICK_REPLIES = [
  { label: "English", value: "english" },
  { label: "Espanol", value: "espanol" },
];

// Every screening / protected-activity question is a yes-or-no question
// (app/intake_engine/mandatory_sweep.py, protected_activity.py) - one tap
// answers it; the text box stays available for anything more to add.
function yesNoQuickReplies(language: string | null): QuickReply[] {
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
    // Scroll only the transcript box, never the whole page (which hid the header).
    const box = transcriptEndRef.current?.parentElement;
    if (box) box.scrollTo({ top: box.scrollHeight, behavior: "smooth" });
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
  const lastQuestion = [...messages].reverse().find((message) => message.role === "assistant");
  const es = state.language === "es";
  const stageOrder = STAGE_ORDER_BY_FLOW[state.flow_version] ?? STAGE_ORDER_BY_FLOW[2];
  const stageIndex = stageOrder.indexOf(state.current_state);
  // Evidence can only be attached once the client has accepted the terms.
  const canUpload = stageIndex > stageOrder.indexOf("terms_acceptance");
  const isYesNo = state.current_state === "mandatory_sweep" || state.current_state === "protected_activity";
  const isLongAnswer = ["story", "general_narrative", "follow_up", "documents"].includes(state.current_state);
  const quickReplies: QuickReply[] = isYesNo
    ? yesNoQuickReplies(state.language)
    : state.current_state === "timeline"
      ? timelineQuickReplies(state.current_question_key, state.language)
      : state.current_state === "follow_up"
        ? [es ? { label: "Omitir esta pregunta", value: "omitir" } : { label: "Skip this question", value: "skip" }]
        : state.current_state === "documents"
          ? [es ? { label: "No tengo documentos", value: "ninguno" } : { label: "I have no documents", value: "none" }]
          : [];
  const placeholder =
    state.current_state === "story" || state.current_state === "general_narrative"
      ? es
        ? "Cuente lo que paso, con sus propias palabras..."
        : "Tell us what happened, in your own words..."
      : state.current_state === "timeline"
        ? es
          ? "Por ejemplo: abril 2023, o 15/04/2023"
          : "For example: April 2023, or 04/15/2023"
        : state.current_state === "documents"
          ? es
            ? "Por ejemplo: talones de pago, mensajes de texto, carta de despido..."
            : "For example: pay stubs, text messages, termination letter..."
          : isYesNo
            ? es
              ? "O escriba mas detalles..."
              : "Or type more detail..."
            : es
              ? "Escriba su respuesta..."
              : "Type your answer..."; 
  const uploadPanel = canUpload ? (
    <UploadPanel
      sessionId={sessionId}
      endUserToken={endUserToken}
      language={state.language}
      onUnauthorized={onUnauthorized}
    />
  ) : null;

  return (
    <div className="p-page p-intake" style={{ maxWidth: 680 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
        <h1 style={{ margin: 0 }}>{es ? "Su admision" : "Your intake"}</h1>
        <button type="button" onClick={onStartOver} style={{ fontSize: "0.85rem" }}>
          New intake / Nueva admision
        </button>
      </div>

      <div className="p-steps">
        {stageOrder.map((stage, index) => {
          const label = STAGE_LABELS[stage][state.language === "es" ? "es" : "en"];
          const isCurrent = index === stageIndex;
          const isPast = stageIndex >= 0 && index < stageIndex;
          return (
            <span
              key={stage}
              className={`p-step${isCurrent ? " is-current" : isPast ? " is-done" : ""}`}
              aria-current={isCurrent ? "step" : undefined}
            >
              {label}
            </span>
          );
        })}
      </div>

      {!isComplete && state.language && lastQuestion && (
        <VoiceInterviewer
          sessionId={sessionId}
          endUserToken={endUserToken}
          language={state.language}
          prompt={lastQuestion.content}
          promptKey={String(lastQuestion.id)}
          onTranscript={(text) => setDraft((current) => (current.trim() ? `${current.trim()} ${text}` : text))}
          onUnauthorized={onUnauthorized}
        />
      )}

      {state.question_number !== null && (
        <div style={{ margin: "1rem 0 0.75rem 0" }}>
          <p className="p-progress-label">
            {state.language === "es"
              ? `Pregunta ${state.question_number} de ${state.total_questions}`
              : `Question ${state.question_number} of ${state.total_questions}`}
            {state.question_number === 1 &&
              (state.flow_version === 1
                ? es
                  ? " - preguntas cortas, casi todas de si o no (unos 5 minutos)."
                  : " - short questions, mostly yes or no (about 5 minutes)."
                : es
                  ? " - primero su historia; despues preguntas cortas (unos 10 minutos)."
                  : " - your story first, then short questions (about 10 minutes).")}
            {state.question_number === state.total_questions &&
              (state.language === "es" ? " - la ultima pregunta." : " - the last question.")}
          </p>
          <div className="p-progress">
            <div style={{ width: `${Math.round(((state.question_number - 1) / state.total_questions) * 100)}%` }} />
          </div>
        </div>
      )}

      <div className="p-transcript" aria-live="polite">
        {messages.map((message) => (
          <div key={message.id} className={`p-bubble ${message.role === "user" ? "is-user" : "is-assistant"}`}>
            {message.content}
          </div>
        ))}
        <div ref={transcriptEndRef} />
      </div>

      {/* A rejected date already says why in the reply itself. */}
      {lastTurnRejected && state.current_state !== "timeline" && (
        <p className="p-note is-warn">
          {state.language === "es"
            ? "No se entendio esa respuesta - por favor intente de nuevo."
            : "That answer wasn't recognized - please try again."}
        </p>
      )}

      {sendError && <ErrorMessage message={sendError} />}

      {isSending && state.current_state === "story" && (
        <p className="p-note p-muted">
          {es ? "Leyendo su historia..." : "Reading your story..."}
        </p>
      )}

      {isComplete ? (
        <>
          <p className="p-done">
            {state.language === "es" ? "Su entrevista ha finalizado. Gracias." : "Your interview is complete. Thank you."}
          </p>
          {uploadPanel}
          <TalkToPerson sessionId={sessionId} endUserToken={endUserToken} language={state.language} onUnauthorized={onUnauthorized} />
          <ReportPanel sessionId={sessionId} endUserToken={endUserToken} language={state.language} />
        </>
      ) : (
        <div style={{ marginTop: "1rem" }}>
          {state.current_state === "language_selection" && (
            <div className="p-quick">
              {LANGUAGE_QUICK_REPLIES.map((option) => (
                <button key={option.value} type="button" onClick={() => handleSend(option.value)} disabled={isSending}>
                  {option.label}
                </button>
              ))}
            </div>
          )}

          {state.current_state === "terms_acceptance" && (
            <div className="p-quick">
              <button type="button" className="p-primary" onClick={() => handleSend(termsQuickReply(state.language).value)} disabled={isSending}>
                {termsQuickReply(state.language).label}
              </button>
            </div>
          )}

          {quickReplies.length > 0 && (
            <div className="p-quick">
              {quickReplies.map((option) => (
                <button key={option.value} type="button" onClick={() => handleSend(option.value)} disabled={isSending}>
                  {option.label}
                </button>
              ))}
            </div>
          )}

          <form onSubmit={handleSubmit} className="p-composer">
            {isLongAnswer ? (
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                disabled={isSending}
                rows={state.current_state === "story" || state.current_state === "general_narrative" ? 6 : 3}
                placeholder={placeholder}
                style={{ resize: "vertical" }}
              />
            ) : (
              <input
                type="text"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                disabled={isSending}
                placeholder={placeholder}
              />
            )}
            <button type="submit" disabled={isSending || draft.trim() === ""} aria-busy={isSending}>
              {isSending ? "..." : state.language === "es" ? "Enviar" : "Send"}
            </button>
          </form>
          {state.language && (
            <TalkToPerson sessionId={sessionId} endUserToken={endUserToken} language={state.language} onUnauthorized={onUnauthorized} />
          )}
          {uploadPanel}
        </div>
      )}
    </div>
  );
}