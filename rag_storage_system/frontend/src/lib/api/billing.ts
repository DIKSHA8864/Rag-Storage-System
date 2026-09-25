import { apiRequest } from "./client";
import type {
  BillingProviderInfo,
  BillingUsageResponse,
  ChangePlanRequest,
  PlanCreateRequest,
  PlanInfo,
  PlanListResponse,
  SubscribeRequest,
  SubscriptionInfo,
} from "./types";

export async function listPlans(token: string): Promise<PlanListResponse> {
  return apiRequest<PlanListResponse>("/admin/billing/plans", { token });
}

export async function createPlan(request: PlanCreateRequest, token: string): Promise<PlanInfo> {
  return apiRequest<PlanInfo>("/admin/billing/plans", { method: "POST", body: request, token });
}

export async function getSubscription(token: string): Promise<SubscriptionInfo> {
  return apiRequest<SubscriptionInfo>("/admin/billing/subscription", { token });
}

export async function subscribe(request: SubscribeRequest, token: string): Promise<SubscriptionInfo> {
  return apiRequest<SubscriptionInfo>("/admin/billing/subscription", { method: "POST", body: request, token });
}

export async function changePlan(request: ChangePlanRequest, token: string): Promise<SubscriptionInfo> {
  return apiRequest<SubscriptionInfo>("/admin/billing/subscription", { method: "PUT", body: request, token });
}

export async function cancelSubscription(token: string): Promise<SubscriptionInfo> {
  return apiRequest<SubscriptionInfo>("/admin/billing/subscription/cancel", { method: "POST", token });
}

export async function getUsage(token: string): Promise<BillingUsageResponse> {
  return apiRequest<BillingUsageResponse>("/admin/billing/usage", { token });
}

export async function getBillingProvider(token: string): Promise<BillingProviderInfo> {
  return apiRequest<BillingProviderInfo>("/admin/billing/provider", { token });
}

/** A Stripe Checkout page for a paid plan - the plan changes only once Stripe confirms payment. */
export async function startCheckout(planSlug: string, token: string): Promise<{ url: string }> {
  return apiRequest<{ url: string }>("/admin/billing/checkout", { method: "POST", body: { plan_slug: planSlug }, token });
}

/** Stripe's Billing Portal (card, invoices, cancel). */
export async function openBillingPortal(token: string): Promise<{ url: string }> {
  return apiRequest<{ url: string }>("/admin/billing/portal", { method: "POST", token });
}
