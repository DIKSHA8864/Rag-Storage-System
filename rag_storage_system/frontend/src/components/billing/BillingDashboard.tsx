"use client";

import { useCallback, useEffect, useState } from "react";

import {
  cancelSubscription,
  changePlan,
  getBillingProvider,
  getSubscription,
  getUsage,
  listPlans,
  openBillingPortal,
  startCheckout,
  subscribe,
} from "@/lib/api/billing";
import { ApiError } from "@/lib/api/client";
import type { BillingProviderInfo, BillingUsageResponse, PlanInfo, SubscriptionInfo } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/useAuth";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

function formatLimit(value: number | null): string {
  return value === null ? "Unlimited" : value.toLocaleString();
}

function formatBytes(value: number | null): string {
  if (value === null) {
    return "Unlimited";
  }
  if (value >= 1_000_000_000) {
    return `${(value / 1_000_000_000).toFixed(1)} GB`;
  }
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)} MB`;
  }
  return `${value.toLocaleString()} B`;
}

function UsageRow({ label, used, limit, formatter = formatLimit }: { label: string; used: number; limit: number | null; formatter?: (v: number | null) => string }) {
  const overLimit = limit !== null && used > limit;

  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "0.4rem 0", borderBottom: "1px solid #f0f0f0" }}>
      <span style={{ fontSize: "0.9rem" }}>{label}</span>
      <span style={{ fontSize: "0.9rem", color: overLimit ? "#b00020" : "inherit" }}>
        {formatter(used)} / {formatter(limit)}
      </span>
    </div>
  );
}

export function BillingDashboard() {
  const { token, logout } = useAuth();

  const [subscription, setSubscription] = useState<SubscriptionInfo | null>(null);
  const [usage, setUsage] = useState<BillingUsageResponse | null>(null);
  const [plans, setPlans] = useState<PlanInfo[]>([]);
  const [hasSubscription, setHasSubscription] = useState(true);

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedPlanSlug, setSelectedPlanSlug] = useState("");
  const [isChangingPlan, setIsChangingPlan] = useState(false);
  const [isCanceling, setIsCanceling] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [provider, setProvider] = useState<BillingProviderInfo | null>(null);
  const [checkoutResult, setCheckoutResult] = useState<string | null>(null);
  const [isRedirecting, setIsRedirecting] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      if (!token) {
        throw new ApiError(401, "Session expired. Please log in again.");
      }

      const [plansResponse, providerResponse] = await Promise.all([listPlans(token), getBillingProvider(token)]);
      setPlans(plansResponse.plans);
      setProvider(providerResponse);
      // Back from Stripe Checkout (?checkout=success|canceled).
      setCheckoutResult(new URLSearchParams(window.location.search).get("checkout"));

      try {
        const subscriptionResponse = await getSubscription(token);
        setSubscription(subscriptionResponse);
        setHasSubscription(true);
        setSelectedPlanSlug(subscriptionResponse.plan.slug);

        const usageResponse = await getUsage(token);
        setUsage(usageResponse);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          setHasSubscription(false);
          setSubscription(null);
          setUsage(null);
        } else {
          throw err;
        }
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(err instanceof ApiError ? err.message : "Could not load billing information.");
    } finally {
      setIsLoading(false);
    }
  }, [token, logout]);

  useEffect(() => {
    // Page-load fetch, same pattern as every other admin page in this app.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  async function handleSubscribeOrChange() {
    if (!selectedPlanSlug) {
      return;
    }

    setActionError(null);
    setIsChangingPlan(true);
    try {
      if (!token) {
        throw new ApiError(401, "Session expired. Please log in again.");
      }
      if (hasSubscription) {
        await changePlan({ plan_slug: selectedPlanSlug }, token);
      } else {
        await subscribe({ plan_slug: selectedPlanSlug }, token);
      }
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setActionError(err instanceof ApiError ? err.message : "Could not update the subscription.");
    } finally {
      setIsChangingPlan(false);
    }
  }

  async function redirectTo(getUrl: () => Promise<{ url: string }>, fallback: string) {
    setActionError(null);
    setIsRedirecting(true);
    try {
      const { url } = await getUrl();
      window.location.href = url;
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setActionError(err instanceof ApiError ? err.message : fallback);
      setIsRedirecting(false);
    }
  }

  async function handleCancel() {
    setActionError(null);
    setIsCanceling(true);
    try {
      if (!token) {
        throw new ApiError(401, "Session expired. Please log in again.");
      }
      await cancelSubscription(token);
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setActionError(err instanceof ApiError ? err.message : "Could not cancel the subscription.");
    } finally {
      setIsCanceling(false);
    }
  }

  if (isLoading) {
    return <LoadingSpinner label="Loading billing information..." />;
  }

  if (error) {
    return <ErrorMessage message={error} />;
  }

  const selectedPlan = plans.find((plan) => plan.slug === selectedPlanSlug);
  const payingThroughStripe = Boolean(provider?.can_manage_billing) && subscription?.status !== "canceled";
  // With Stripe on, a paid plan is started by paying on Stripe's page, not by assignment.
  const needsCheckout = Boolean(provider?.checkout_enabled && selectedPlan && selectedPlan.price_cents > 0 && !payingThroughStripe);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem", maxWidth: 720 }}>
      {checkoutResult === "success" && (
        <p role="status" style={{ background: "#eaf6ea", padding: "0.6rem 0.8rem", borderRadius: 4, margin: 0 }}>
          Payment submitted to Stripe. Your plan changes here as soon as Stripe confirms it (usually within seconds).{" "}
          <button type="button" onClick={load}>
            Refresh
          </button>
        </p>
      )}
      {checkoutResult === "canceled" && (
        <p role="status" style={{ background: "#f5f5f5", padding: "0.6rem 0.8rem", borderRadius: 4, margin: 0 }}>
          Checkout was canceled - nothing was charged and your plan is unchanged.
        </p>
      )}
      <section>
        <h3 style={{ fontSize: "0.95rem", margin: "0 0 0.5rem 0" }}>Current plan</h3>
        {!hasSubscription && (
          <p style={{ color: "#777", fontSize: "0.85rem" }}>
            This firm has not been assigned a plan yet. Choose one below to get started.
          </p>
        )}
        {subscription && (
          <div style={{ border: "1px solid #e5e5e5", borderRadius: 4, padding: "0.75rem 1rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <strong>{subscription.plan.name}</strong>
              <span
                style={{
                  fontSize: "0.8rem",
                  padding: "0.1rem 0.5rem",
                  borderRadius: 12,
                  background: subscription.status === "active" ? "#eaf6ea" : subscription.status === "trialing" ? "#eaf1fb" : "#fdeaea",
                }}
              >
                {subscription.status}
              </span>
            </div>
            {subscription.plan.description && (
              <p style={{ color: "#666", fontSize: "0.85rem", margin: "0.4rem 0" }}>{subscription.plan.description}</p>
            )}
            <p style={{ color: "#777", fontSize: "0.8rem", margin: "0.4rem 0 0 0" }}>
              Current period: {subscription.current_period_start} &rarr; {subscription.current_period_end}
            </p>
            {subscription.canceled_at && (
              <p style={{ color: "#b00020", fontSize: "0.8rem", margin: "0.4rem 0 0 0" }}>
                Canceled at {subscription.canceled_at}
              </p>
            )}
          </div>
        )}
      </section>

      {usage && (
        <section>
          <h3 style={{ fontSize: "0.95rem", margin: "0 0 0.5rem 0" }}>Usage this period</h3>
          <div>
            <UsageRow label="Matters" used={usage.usage.matters} limit={usage.limits?.max_matters ?? null} />
            <UsageRow label="Documents" used={usage.usage.documents} limit={usage.limits?.max_documents ?? null} />
            <UsageRow
              label="Storage"
              used={usage.usage.storage_bytes}
              limit={usage.limits?.max_storage_bytes ?? null}
              formatter={formatBytes}
            />
            <UsageRow
              label="LLM calls (this billing period)"
              used={usage.usage.llm_calls_per_month}
              limit={usage.limits?.max_llm_calls_per_month ?? null}
            />
          </div>
        </section>
      )}

      <section>
        <h3 style={{ fontSize: "0.95rem", margin: "0 0 0.5rem 0" }}>{hasSubscription ? "Change plan" : "Choose a plan"}</h3>
        {actionError && <ErrorMessage message={actionError} />}
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <select value={selectedPlanSlug} onChange={(e) => setSelectedPlanSlug(e.target.value)}>
            <option value="" disabled>
              Select a plan
            </option>
            {plans.map((plan) => (
              <option key={plan.slug} value={plan.slug}>
                {plan.name} {plan.price_cents > 0 ? `- $${(plan.price_cents / 100).toFixed(2)}/${plan.billing_interval}` : "- Free"}
              </option>
            ))}
          </select>
          {needsCheckout ? (
            <button
              type="button"
              onClick={() => redirectTo(() => startCheckout(selectedPlanSlug, token ?? ""), "Could not open Stripe Checkout.")}
              disabled={isRedirecting || selectedPlanSlug === subscription?.plan.slug}
            >
              {isRedirecting ? "Opening Stripe..." : "Pay with card (Stripe)"}
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSubscribeOrChange}
              disabled={isChangingPlan || !selectedPlanSlug || (hasSubscription && selectedPlanSlug === subscription?.plan.slug)}
            >
              {isChangingPlan ? "Saving..." : hasSubscription ? "Switch plan" : "Subscribe"}
            </button>
          )}
          {provider?.can_manage_billing && (
            <button
              type="button"
              onClick={() => redirectTo(() => openBillingPortal(token ?? ""), "Could not open the Stripe billing portal.")}
              disabled={isRedirecting}
            >
              Manage billing (card, invoices)
            </button>
          )}
          {hasSubscription && subscription?.status !== "canceled" && (
            <button type="button" onClick={handleCancel} disabled={isCanceling}>
              {isCanceling ? "Canceling..." : "Cancel subscription"}
            </button>
          )}
        </div>
        {provider?.checkout_enabled && (
          <p style={{ fontSize: "0.8rem", color: "#666", marginTop: "0.5rem" }}>
            Payments are handled by Stripe - card details never reach this system.
          </p>
        )}
      </section>
    </div>
  );
}
