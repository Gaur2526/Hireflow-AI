/**
 * Mirrors the FastAPI response models in `backend/app/schemas`.
 * Keep the two in sync — the backend is the source of truth.
 */

export type ParsedBy = "llm" | "heuristic";
export type AnswerType = "string" | "boolean" | "number" | "enum";

export interface JobCriteria {
  role_title: string;
  titles: string[];
  seniority: string[];
  must_have_skills: string[];
  nice_to_have_skills: string[];
  min_years: number | null;
  max_years: number | null;
  locations: string[];
  countries: string[];
  industries: string[];
  target_companies: string[];
  education: string[];
  employment_type: string | null;
  work_mode: string | null;
  compensation: string | null;
  summary: string;
}

export interface ScreeningQuestion {
  key: string;
  question: string;
  answer_type: AnswerType;
  options: string[];
  rationale: string;
  required: boolean;
}

export interface ScreeningPlan {
  questions: ScreeningQuestion[];
  objective: string;
  introduction: string;
  agent_prompt: string;
  result_prompt: string;
  result_schema: Record<string, string>;
}

export interface Job {
  id: string;
  title: string;
  company: string | null;
  location: string | null;
  description: string;
  status: string;
  criteria: JobCriteria;
  screening_questions: ScreeningQuestion[];
  result_schema: Record<string, string>;
  parsed_by: ParsedBy | null;
  created_at: string;
  updated_at: string;
}

export interface JobSummary {
  id: string;
  title: string;
  company: string | null;
  location: string | null;
  status: string;
  parsed_by: ParsedBy | null;
  created_at: string;
  candidate_count: number;
  shortlisted_count: number;
  campaign_count: number;
  call_count: number;
}

export interface ParsePreview {
  criteria: JobCriteria;
  screening_plan: ScreeningPlan;
  parsed_by: ParsedBy;
  warnings: string[];
}

export type CandidateStatus =
  | "SOURCED"
  | "SHORTLISTED"
  | "REJECTED"
  | "QUEUED"
  | "CALLING"
  | "COMPLETED"
  | "UNREACHABLE";

export interface Candidate {
  id: string;
  job_id: string;
  source: string;
  external_id: string | null;
  full_name: string;
  first_name: string | null;
  last_name: string | null;
  headline: string | null;
  title: string | null;
  company: string | null;
  location: string | null;
  country_code: string | null;
  linkedin_url: string | null;
  email: string | null;
  phone: string | null;
  phone_is_valid: boolean;
  years_experience: number | null;
  seniority: string | null;
  skills: string[];
  experience: Array<Record<string, unknown>>;
  education: Array<Record<string, unknown>>;
  fit_score: number;
  fit_breakdown: {
    score?: number;
    breakdown?: Record<string, number>;
    matched_must_have?: string[];
    missing_must_have?: string[];
    matched_nice_to_have?: string[];
  };
  fit_reasons: string[];
  status: CandidateStatus;
  created_at: string;
}

export interface SearchRun {
  id: string;
  job_id: string;
  provider: string;
  query: Record<string, unknown>;
  total_available: number | null;
  returned: number;
  new_candidates: number;
  latency_ms: number | null;
  error: string | null;
  created_at: string;
}

export interface SearchResponse {
  run: SearchRun;
  candidates: Candidate[];
  warnings: string[];
  provider_label: string;
}

export type CallStatus =
  | "PENDING"
  | "NOT_STARTED"
  | "SCHEDULED"
  | "INITIATED"
  | "RINGING"
  | "IN_PROGRESS"
  | "COMPLETED"
  | "NOT_CONNECTED"
  | "CANCELLED"
  | "FAILED";

export interface Call {
  id: string;
  campaign_id: string;
  candidate_id: string;
  hunar_call_id: string | null;
  request_id: string | null;
  status: CallStatus;
  lifecycle_status: string | null;
  engagement_status: string | null;
  answered_by: string | null;
  call_ended_by: string | null;
  dialed_number: string | null;
  dialed_redirected: boolean;
  duration_seconds: number | null;
  user_speech_duration: number | null;
  recording_url: string | null;
  result: Record<string, unknown>;
  // Any JSON: the backend types this dict[str, Any] and merges whatever a
  // webhook body echoes back.
  custom_data: Record<string, unknown>;
  retry_count: number;
  error: string | null;
  started_at: string | null;
  ended_at: string | null;
  last_synced_at: string | null;
  sync_source: string | null;
  created_at: string;
  updated_at: string;
  candidate_name: string;
  candidate_title: string | null;
  candidate_company: string | null;
  candidate_linkedin: string | null;
  candidate_fit_score: number;
}

export interface CampaignStats {
  total: number;
  pending: number;
  in_flight: number;
  completed: number;
  not_connected: number;
  failed: number;
  cancelled: number;
  answered_human: number;
  consented: number;
  interested: number;
  do_not_contact: number;
  avg_duration_seconds: number | null;
  total_talk_minutes: number;
}

export interface Campaign {
  id: string;
  job_id: string;
  name: string;
  status: "DRAFT" | "AGENT_READY" | "RUNNING" | "COMPLETED" | "FAILED";
  hunar_agent_id: string | null;
  agent_config: Record<string, unknown>;
  result_schema: Record<string, string>;
  call_defaults: Record<string, unknown>;
  request_id: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface AnswerColumn {
  key: string;
  label: string;
  type: "string" | "boolean" | "number" | "enum";
  description: string;
}

export interface CampaignDetail {
  campaign: Campaign;
  job_title: string;
  job_id: string;
  stats: CampaignStats;
  calls: Call[];
  answer_columns: AnswerColumn[];
  warnings: string[];
}

export interface CampaignSummary {
  id: string;
  job_id: string;
  name: string;
  status: Campaign["status"];
  hunar_agent_id: string | null;
  created_at: string;
  job_title: string;
  stats: CampaignStats;
}

export interface LaunchResponse {
  campaign: Campaign;
  dispatched: number;
  skipped: Array<{ candidate_id: string; name: string; reason: string }>;
  warnings: string[];
}

export interface ProviderStatus {
  name: string;
  label: string;
  docs_url: string;
  requires_key: boolean;
  configured: boolean;
  retired: boolean;
  note: string;
  active: boolean;
}

export interface AppConfig {
  app_name: string;
  environment: string;
  people_provider: string;
  providers: ProviderStatus[];
  hunar: {
    configured: boolean;
    key_fingerprint: string;
    base_url: string;
    webhook_secret_set: boolean;
  };
  llm: { configured: boolean; model: string | null };
  webhooks: {
    available: boolean;
    public_base_url: string | null;
    poll_interval_seconds: number;
  };
  demo_call_redirect: { enabled: boolean; number: string | null };
  voice_options: {
    personas: string[];
    languages: string[];
    timezones: string[];
    allowed_days: string[];
  };
  defaults: {
    voice_persona: string;
    language: string;
    timezone: string;
    country_code: string;
    max_candidates_per_search: number;
  };
}

export interface DashboardOverview {
  totals: {
    jobs: number;
    candidates: number;
    shortlisted: number;
    campaigns: number;
    calls: number;
  };
  call_stats: CampaignStats;
  recent_jobs: Array<{
    id: string;
    title: string;
    company: string | null;
    status: string;
    created_at: string;
  }>;
  recent_campaigns: Array<{
    id: string;
    name: string;
    job_id: string;
    status: string;
    created_at: string;
    stats: CampaignStats;
  }>;
}

export interface CallDefaults {
  timezone: string;
  max_retry_count: number;
  retry_interval_hours: number;
  allowed_days: string[];
  earliest_call_time: string;
  last_call_time: string;
  from_phone_number?: string | null;
}

export interface AgentConfigInput {
  language: string;
  voice_persona: string;
  persona_name?: string | null;
  introduction?: string | null;
  agent_prompt?: string | null;
  objective?: string | null;
  result_prompt?: string | null;
  questions?: ScreeningQuestion[] | null;
}

export interface WebhookEvent {
  id: string;
  event_type: string | null;
  hunar_call_id: string | null;
  signature_valid: boolean | null;
  handled: boolean;
  note: string | null;
  received_at: string;
}
