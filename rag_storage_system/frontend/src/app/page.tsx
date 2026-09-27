"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Icon, type IconName } from "@/components/ui/Icon";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { useAuth } from "@/lib/auth/useAuth";
import { loadEndUserSession } from "@/lib/clientAuth/endUserSessionStorage";
import { END_USER_HOME, STAFF_HOME } from "@/lib/sessionIdentity";

const FEATURES: { icon: IconName; title: string; text: string }[] = [
  {
    icon: "book",
    title: "Answers from the firm's library",
    text: "Every answer is drawn only from the statutes, cases and guides your firm has chosen - with the source cited. If the library doesn't cover a point, you are told so plainly.",
  },
  {
    icon: "intake",
    title: "A guided intake",
    text: "Tell your story once, one question at a time. The firm's attorneys receive an organised summary instead of a pile of emails.",
  },
  {
    icon: "shield",
    title: "Private by design",
    text: "Your questions, answers and documents are visible only to you and your firm. Each firm's data is kept strictly separate.",
  },
];

const STEPS: { title: string; text: string }[] = [
  { title: "Create your account", text: "Use the email address your firm has on file." },
  { title: "Ask or start your intake", text: "Ask a question in plain words, or answer the intake interview about your situation." },
  { title: "The firm follows up", text: "An attorney reviews what you shared and contacts you about next steps." },
];

/** Entry point: an already signed-in administrator goes straight to the dashboard; everyone else sees the welcome page. */
export default function HomePage() {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isLoading) return;
    if (isAuthenticated) {
      router.replace(STAFF_HOME);
    } else if (loadEndUserSession()) {
      router.replace(END_USER_HOME);
    }
  }, [isLoading, isAuthenticated, router]);

  if (isLoading || isAuthenticated) {
    return <LoadingSpinner />;
  }

  return (
    <div className="c-landing">
      <section className="c-hero">
        <div className="c-hero-inner">
          <div>
            <p className="c-eyebrow">Legal research for your firm&apos;s clients</p>
            <h1>Clear answers, grounded in your firm&apos;s own legal library.</h1>
            <p className="c-lead">
              AshiLegal lets you ask legal questions and share the details of your matter with your law firm - securely, in one
              place, at any hour.
            </p>
            <div className="c-hero-actions">
              <Link href="/portal/login" className="c-cta">
                Client sign in
              </Link>
              <Link href="/portal/signup" className="c-cta c-cta-ghost">
                Create your account
              </Link>
            </div>
            <p className="c-hero-note">
              Firm staff? <Link href="/login">Sign in to the firm console</Link>
            </p>
          </div>

          {/* An illustration of an answer, not live data. */}
          <div className="c-hero-card" aria-hidden>
            <div className="c-hero-q">
              <Icon name="ask" size={16} /> Can my employer end my contract while I am on medical leave?
            </div>
            <div className="c-hero-a">
              <span className="c-line" style={{ width: "92%" }} />
              <span className="c-line" style={{ width: "86%" }} />
              <span className="c-line" style={{ width: "64%" }} />
              <div className="c-hero-src">
                <Icon name="book" size={14} /> Source: firm library
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="c-section" aria-labelledby="features-title">
        <h2 id="features-title" className="c-section-title">
          What you can do here
        </h2>
        <div className="c-features">
          {FEATURES.map((feature) => (
            <article key={feature.title} className="c-feature">
              <span className="c-feature-icon">
                <Icon name={feature.icon} size={22} />
              </span>
              <h3>{feature.title}</h3>
              <p>{feature.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="c-section" aria-labelledby="how-title">
        <h2 id="how-title" className="c-section-title">
          How it works
        </h2>
        <ol className="c-how">
          {STEPS.map((step, index) => (
            <li key={step.title}>
              <span className="c-how-num">{index + 1}</span>
              <div>
                <h3>{step.title}</h3>
                <p>{step.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <footer className="c-footer">
        <div className="c-footer-inner">
          <span>© {new Date().getFullYear()} AshiLegal</span>
          <span>Information here is not legal advice. Your attorney will advise you on your matter.</span>
        </div>
      </footer>
    </div>
  );
}
