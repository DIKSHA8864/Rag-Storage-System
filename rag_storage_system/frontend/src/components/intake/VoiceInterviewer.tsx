"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api/client";
import { getVoiceCapabilities, transcribeAnswer } from "@/lib/api/voice";

interface VoiceInterviewerProps {
  sessionId: number;
  endUserToken: string;
  language: string | null;
  /** The question on screen - read aloud whenever `promptKey` changes while voice is on. */
  prompt: string;
  promptKey: string;
  /** A spoken answer, transcribed - goes into the answer box for the client to check before sending. */
  onTranscript: (text: string) => void;
  onUnauthorized: () => void;
}

const TEXT = {
  en: {
    voiceOn: "Read questions aloud",
    repeat: "Repeat question",
    speak: "Answer by voice",
    stop: "Stop - use this answer",
    transcribing: "Writing down your answer...",
    check: "Check the text below, change anything that's wrong, then press Send.",
    noVoice: "Your browser can't read questions aloud - they are shown as text.",
    noMic: "Microphone not available - please type your answer.",
    presenter: "Your intake assistant",
  },
  es: {
    voiceOn: "Leer las preguntas en voz alta",
    repeat: "Repetir la pregunta",
    speak: "Responder con la voz",
    stop: "Detener - usar esta respuesta",
    transcribing: "Escribiendo su respuesta...",
    check: "Revise el texto de abajo, corrija lo que sea necesario y presione Enviar.",
    noVoice: "Su navegador no puede leer las preguntas en voz alta - se muestran como texto.",
    noMic: "Micrófono no disponible - por favor escriba su respuesta.",
    presenter: "Su asistente de admisión",
  },
};

function pickVoice(lang: string): SpeechSynthesisVoice | undefined {
  const voices = window.speechSynthesis.getVoices();
  return voices.find((v) => v.lang === lang) ?? voices.find((v) => v.lang.startsWith(lang.slice(0, 2)));
}

/** A friendly animated presenter: blinks, and its mouth moves while a question is being read. */
function Presenter({ speaking, label }: { speaking: boolean; label: string }) {
  return (
    <svg width="72" height="72" viewBox="0 0 72 72" role="img" aria-label={label}>
      <circle cx="36" cy="36" r="34" fill="#eaf1fb" stroke="#1a5fb4" strokeWidth="2" />
      <circle cx="36" cy="30" r="16" fill="#f6d7b8" />
      <path d="M20 27 Q36 8 52 27 Q48 16 36 15 Q24 16 20 27Z" fill="#5b3a29" />
      <path d="M14 66 Q36 44 58 66" fill="#1a5fb4" />
      {[30, 42].map((x) => (
        <ellipse key={x} cx={x} cy="29" rx="1.8" ry="2.2" fill="#333">
          <animate attributeName="ry" values="2.2;2.2;0.2;2.2" keyTimes="0;0.92;0.96;1" dur="4s" repeatCount="indefinite" />
        </ellipse>
      ))}
      <ellipse cx="36" cy="38" rx="4" ry={speaking ? 2.5 : 1} fill="#9c3d3d">
        {speaking && <animate attributeName="ry" values="1;3;1.5;3.2;1" dur="0.6s" repeatCount="indefinite" />}
      </ellipse>
    </svg>
  );
}

/**
 * Voice mode for the interview. Questions are read aloud by the
 * browser's own speech synthesis (nothing leaves the device). Spoken
 * answers are transcribed by the firm's configured speech-to-text and
 * put in the answer box - the client checks the text and sends it
 * themselves, so nothing they didn't approve is recorded.
 */
export function VoiceInterviewer({
  sessionId,
  endUserToken,
  language,
  prompt,
  promptKey,
  onTranscript,
  onUnauthorized,
}: VoiceInterviewerProps) {
  const t = TEXT[language === "es" ? "es" : "en"];
  const speechLang = language === "es" ? "es-US" : "en-US";
  const canSpeak = typeof window !== "undefined" && "speechSynthesis" in window;

  const [voiceOn, setVoiceOn] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [sttAvailable, setSttAvailable] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);

  useEffect(() => {
    getVoiceCapabilities(endUserToken)
      .then((caps) => setSttAvailable(caps.speech_to_text))
      .catch(() => setSttAvailable(false));
  }, [endUserToken]);

  const speak = useCallback(
    (text: string) => {
      if (!canSpeak || !text) return;
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = speechLang;
      const voice = pickVoice(speechLang);
      if (voice) utterance.voice = voice;
      utterance.rate = 0.95;
      utterance.onstart = () => setSpeaking(true);
      utterance.onend = () => setSpeaking(false);
      utterance.onerror = () => setSpeaking(false);
      window.speechSynthesis.speak(utterance);
    },
    [canSpeak, speechLang]
  );

  // A new question while voice mode is on -> read it.
  useEffect(() => {
    if (voiceOn) speak(prompt);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [promptKey, voiceOn]);

  useEffect(() => () => {
    if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
    recorderRef.current?.stream.getTracks().forEach((track) => track.stop());
  }, []);

  async function startRecording() {
    setNote(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        setIsRecording(false);
        setIsTranscribing(true);
        try {
          const text = await transcribeAnswer(sessionId, new Blob(chunks, { type: recorder.mimeType }), endUserToken);
          if (text) {
            onTranscript(text);
            setNote(t.check);
          }
        } catch (err) {
          if (err instanceof ApiError && err.status === 401) {
            onUnauthorized();
            return;
          }
          setNote(err instanceof ApiError ? err.message : t.noMic);
        } finally {
          setIsTranscribing(false);
        }
      };
      window.speechSynthesis?.cancel();
      recorderRef.current = recorder;
      recorder.start();
      setIsRecording(true);
    } catch {
      setNote(t.noMic);
    }
  }

  return (
    <div
      style={{
        display: "flex",
        gap: "0.75rem",
        alignItems: "center",
        border: "1px solid #e5e5e5",
        borderRadius: 6,
        padding: "0.5rem 0.75rem",
        margin: "0 0 0.75rem 0",
      }}
    >
      <Presenter speaking={speaking} label={t.presenter} />
      <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem", flex: 1 }}>
        {canSpeak ? (
          <label style={{ fontSize: "0.85rem" }}>
            <input
              type="checkbox"
              checked={voiceOn}
              onChange={(e) => {
                setVoiceOn(e.target.checked);
                if (!e.target.checked) window.speechSynthesis.cancel();
              }}
            />{" "}
            {t.voiceOn}
          </label>
        ) : (
          <span style={{ fontSize: "0.8rem", color: "#777" }}>{t.noVoice}</span>
        )}
        <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
          {canSpeak && (
            <button type="button" onClick={() => speak(prompt)} disabled={!prompt}>
              {t.repeat}
            </button>
          )}
          {sttAvailable &&
            (isRecording ? (
              <button type="button" onClick={() => recorderRef.current?.stop()} style={{ color: "#b3261e" }}>
                ● {t.stop}
              </button>
            ) : (
              <button type="button" onClick={startRecording} disabled={isTranscribing}>
                {isTranscribing ? t.transcribing : t.speak}
              </button>
            ))}
        </div>
        {note && <span style={{ fontSize: "0.8rem", color: "#555" }}>{note}</span>}
      </div>
    </div>
  );
}
