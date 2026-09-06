/**
 * Typed client for the FastAPI backend.
 *
 * The backend returns errors as `{ error: { code, message, details? } }`, so a
 * failed request surfaces the server's own wording rather than "500".
 */

import type {
  AgentConfigInput,
  AppConfig,
  Call,
  CallDefaults,
  Campaign,
  CampaignDetail,
  CampaignSummary,
  Candidate,
  DashboardOverview,
  Job,
  JobSummary,
  LaunchResponse,
  ParsePreview,
  ScreeningPlan,
  ScreeningQuestion,
  SearchResponse,
  SearchRun,
  WebhookEvent,
} from "./types";

export const API_BASE = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string = "error",
    readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal } = options;

  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api${path}`, {
      method,
      signal,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch (cause) {
    if ((cause as Error)?.name === "AbortError") throw cause;
    throw new ApiError(
      `Cannot reach the API at ${API_BASE}. Is the backend running?`,
      0,
      "network_error",
    );
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    const envelope = (payload as { error?: { message?: string; code?: string; details?: unknown } })
      ?.error;
    // A 422's message is a fixed sentence; the field-level reason the operator
    // needs to act on only exists in `details`, so fold it into the message.
    const detail = Array.isArray(envelope?.details)
      ? (envelope.details as { field?: string; message?: string }[])
          .map((d) => [d.field, d.message].filter(Boolean).join(": "))
          .filter(Boolean)
          .join("; ")
      : "";
    const message = envelope?.message ?? `Request failed with HTTP ${response.status}`;
    throw new ApiError(
      detail ? `${message} ${detail}` : message,
      response.status,
      envelope?.code ?? "error",
      envelope?.details,
    );
  }

  return payload as T;
}

// --- meta ------------------------------------------------------------------
export const getConfig = () => request<AppConfig>("/meta/config");

export const getHealth = () =>
  request<{
    status: string;
    environment: string;
    database: { ok: boolean; error: string | null };
    hunar_configured: boolean;
    llm_configured: boolean;
    people_provider: string;
    webhooks_available: boolean;
  }>("/meta/health");

export const pingHunar = () =>
  request<{ ok: boolean; agents_visible?: number; reason?: string; key?: string }>(
    "/meta/hunar/ping",
  );

export const listHunarAgents = (pageSize = 20) =>
  request<{ count: number; results: Array<Record<string, unknown>> }>(
    `/meta/hunar/agents?page_size=${pageSize}`,
  );

export const listWebhookEvents = (limit = 25) =>
  request<WebhookEvent[]>(`/webhooks/hunar/events?limit=${limit}`);

// --- jobs ------------------------------------------------------------------
export const parseJobDescription = (
  body: { title?: string; company?: string; location?: string; description: string },
  signal?: AbortSignal,
) => request<ParsePreview>("/jobs/parse", { method: "POST", body, signal });

export const createJob = (body: {
  title?: string;
  company?: string;
  location?: string;
  description: string;
}) => request<Job>("/jobs", { method: "POST", body });

export const listJobs = () => request<JobSummary[]>("/jobs");
export const getJob = (id: string) => request<Job>(`/jobs/${id}`);
export const deleteJob = (id: string) =>
  request<{ ok: boolean }>(`/jobs/${id}`, { method: "DELETE" });

export const updateJob = (
  id: string,
  body: Partial<Pick<Job, "title" | "company" | "location" | "description">> & {
    criteria?: Job["criteria"];
    screening_questions?: ScreeningQuestion[];
  },
) => request<Job>(`/jobs/${id}`, { method: "PATCH", body });

export const reparseJob = (id: string) =>
  request<Job>(`/jobs/${id}/reparse`, { method: "POST" });

export const getScreeningPlan = (id: string) =>
  request<ScreeningPlan>(`/jobs/${id}/screening-plan`);

// --- candidates ------------------------------------------------------------
export const searchCandidates = (
  jobId: string,
  body: {
    provider?: string;
    limit?: number;
    titles?: string[];
    must_have_skills?: string[];
    locations?: string[];
    min_years?: number | null;
    max_years?: number | null;
    require_phone?: boolean;
    replace_existing?: boolean;
  },
) => request<SearchResponse>(`/jobs/${jobId}/search`, { method: "POST", body });

export const listCandidates = (jobId: string) =>
  request<Candidate[]>(`/jobs/${jobId}/candidates`);

export const listSearchRuns = (jobId: string) =>
  request<SearchRun[]>(`/jobs/${jobId}/searches`);

export const setShortlist = (jobId: string, candidateIds: string[], status = "SHORTLISTED") =>
  request<Candidate[]>(`/jobs/${jobId}/shortlist`, {
    method: "POST",
    body: { candidate_ids: candidateIds, status },
  });

export const setCandidatePhone = (candidateId: string, phone: string) =>
  request<Candidate>(`/candidates/${candidateId}/phone`, {
    method: "PATCH",
    body: { phone },
  });

// --- campaigns -------------------------------------------------------------
export const launchCampaign = (
  jobId: string,
  body: {
    name?: string;
    candidate_ids?: string[];
    agent_config?: AgentConfigInput;
    call_defaults?: CallDefaults;
    reuse_agent_id?: string | null;
    dry_run?: boolean;
  },
) => request<LaunchResponse>(`/jobs/${jobId}/campaigns`, { method: "POST", body });

export const dispatchCampaign = (id: string) =>
  request<LaunchResponse>(`/campaigns/${id}/dispatch`, { method: "POST" });

export const listCampaigns = (jobId?: string) =>
  request<CampaignSummary[]>(`/campaigns${jobId ? `?job_id=${jobId}` : ""}`);

export const getCampaign = (id: string, signal?: AbortSignal) =>
  request<CampaignDetail>(`/campaigns/${id}`, { signal });

export const syncCampaign = (id: string) =>
  request<CampaignDetail>(`/campaigns/${id}/sync`, { method: "POST" });

export const getCall = (campaignId: string, callId: string) =>
  request<Call>(`/campaigns/${campaignId}/calls/${callId}`);

export const deleteCampaign = (id: string) =>
  request<{ ok: boolean }>(`/campaigns/${id}`, { method: "DELETE" });

export const campaignCsvUrl = (id: string) =>
  `${API_BASE}/api/campaigns/${id}/export.csv`;

// --- dashboard -------------------------------------------------------------
export const getOverview = () => request<DashboardOverview>("/dashboard/overview");

export type { Campaign, Job };
