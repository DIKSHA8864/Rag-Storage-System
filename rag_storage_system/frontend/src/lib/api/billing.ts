import { apiRequest } from "./client";
import type {
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
