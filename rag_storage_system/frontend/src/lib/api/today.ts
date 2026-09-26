import { apiRequest } from "./client";

export interface TodayIntakeInfo {
  intake_session_id: number;
  matter_id: number;
  matter_name: string;
  client_email: string | null;
  title: string;
  stage: string;
  created_at: string;
}

export interface TodayResponse {
  since: string;
  new_intakes: TodayIntakeInfo[];
  intakes_started: number;
  intakes_completed: number;
  questions_asked: number;
  no_authority: number;
  reports_pending: number;
  requests_open: number;
  requests_claimed: number;
  library_uploads: number;
  case_documents: number;
  client_uploads: number;
}

/** GET /admin/today - since the start of the viewer's own day (app/api/today_api.py). */
export async function getToday(token: string): Promise<TodayResponse> {
  const midnight = new Date();
  midnight.setHours(0, 0, 0, 0);
  return apiRequest<TodayResponse>(`/admin/today?since=${encodeURIComponent(midnight.toISOString())}`, { token });
}
