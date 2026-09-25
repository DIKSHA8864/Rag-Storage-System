"use client";

import { useEffect, useState, type FormEvent } from "react";

import { ApiError } from "@/lib/api/client";
import { getMyHandoff, requestHandoff } from "@/lib/api/voice";
import type { HandoffInfo } from "@/lib/api/types";

interface TalkToPersonProps {
  sessionId: number;
  endUserToken: string;
  language: string | null;
  onUnauthorized: () => void;
}

const TEXT = {
  en: {
    button: "Talk to a person",
    intro: "Someone from the firm will contact you. How should we reach you?",
    phone: "Phone call",
    video: "Video call",
    email: "Email",
    contact: "Phone number or email",
    when: "Best time to reach you (optional)",
    message: "Anything you'd like us to know first (optional)",
    send: "Send request",
    cancel: "Cancel",
    waiting: "Your request was sent. Someone from the firm will contact you",
    claimed: "A person from the firm is handling your request and will contact you",
    closed: "Your earlier request was completed. You can ask again anytime.",
  },
  es: {
    button: "Hablar con una persona",
    intro: "Alguien del despacho se comunicará con usted. ¿Cómo prefiere que lo contactemos?",
    phone: "Llamada telefónica",
    video: "Videollamada",
    email: "Correo electrónico",
    contact: "Número de teléfono o correo",
    when: "Mejor horario para contactarlo (opcional)",
    message: "Algo que quiera contarnos primero (opcional)",
    send: "Enviar solicitud",
    cancel: "Cancelar",
    waiting: "Su solicitud fue enviada. Alguien del despacho se comunicará con usted",
    claimed: "Una persona del despacho está atendiendo su solicitud y se comunicará con usted",
    closed: "Su solicitud anterior fue atendida. Puede pedir otra en cualquier momento.",
  },
};

/** Ask for a human at any point in the intake - it goes to the firm's queue (Admin -> Requests). */
export function TalkToPerson({ sessionId, endUserToken, language, onUnauthorized }: TalkToPersonProps) {
  const t = TEXT[language === "es" ? "es" : "en"];
  const [request, setRequest] = useState<HandoffInfo | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [method, setMethod] = useState<"phone" | "video" | "email">("phone");
  const [contact, setContact] = useState("");
  const [when, setWhen] = useState("");
  const [message, setMessage] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMyHandoff(endUserToken)
      .then(setRequest)
      .catch(() => setRequest(null));
  }, [endUserToken]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setIsSending(true);
    setError(null);
    try {
      const created = await requestHandoff(
        {
          intake_session_id: sessionId,
          contact_method: method,
          contact_value: contact,
          preferred_time: when || null,
          message: message || null,
          language: language === "es" ? "es" : "en",
        },
        endUserToken
      );
      setRequest(created);
      setIsOpen(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onUnauthorized();
        return;
      }
      setError(err instanceof ApiError ? err.message : "Could not send your request.");
    } finally {
      setIsSending(false);
    }
  }

  const active = request && request.status !== "closed";

  if (active) {
    return (
      <p role="status" style={{ background: "#eaf1fb", padding: "0.5rem 0.75rem", borderRadius: 4, fontSize: "0.85rem" }}>
        {request.status === "claimed" ? t.claimed : t.waiting} ({request.contact_value}).
      </p>
    );
  }

  return (
    <div style={{ margin: "0.5rem 0" }}>
      {!isOpen ? (
        <>
          {request?.status === "closed" && <p style={{ fontSize: "0.8rem", color: "#666", margin: "0 0 0.3rem 0" }}>{t.closed}</p>}
          <button type="button" onClick={() => setIsOpen(true)}>
            {t.button}
          </button>
        </>
      ) : (
        <form
          onSubmit={handleSubmit}
          style={{ border: "1px solid #e5e5e5", borderRadius: 6, padding: "0.75rem", display: "flex", flexDirection: "column", gap: "0.4rem" }}
        >
          <p style={{ margin: 0, fontSize: "0.9rem" }}>{t.intro}</p>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", fontSize: "0.85rem" }}>
            {(["phone", "video", "email"] as const).map((option) => (
              <label key={option}>
                <input type="radio" name="contact-method" checked={method === option} onChange={() => setMethod(option)} /> {t[option]}
              </label>
            ))}
          </div>
          <input aria-label={t.contact} placeholder={t.contact} value={contact} onChange={(e) => setContact(e.target.value)} required />
          <input aria-label={t.when} placeholder={t.when} value={when} onChange={(e) => setWhen(e.target.value)} />
          <textarea aria-label={t.message} placeholder={t.message} rows={2} value={message} onChange={(e) => setMessage(e.target.value)} />
          {error && <p style={{ color: "#b3261e", fontSize: "0.85rem", margin: 0 }}>{error}</p>}
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button type="submit" disabled={isSending || !contact.trim()}>
              {isSending ? "..." : t.send}
            </button>
            <button type="button" onClick={() => setIsOpen(false)}>
              {t.cancel}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
