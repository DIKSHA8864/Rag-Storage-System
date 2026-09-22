import { apiRequest } from "./client";
import type { LoginRequest, LoginResponse } from "./types";

export async function login(credentials: LoginRequest): Promise<LoginResponse> {
  return apiRequest<LoginResponse>("/auth/login", {
    method: "POST",
    body: credentials,
  });
}