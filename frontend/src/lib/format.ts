import type { Call, CallStatus, CandidateStatus } from "./types";

/** Values Hunar's extractor uses when the candidate never said anything usable. */
const SENTINELS = new Set([
  "not available",
  "not discussed",
  "not provided",
  "unknown",
  "n/a",
  "none",
  "null",
]);

export function isBlankAnswer(value: unknown): boolean {
  if (value === null || value === undefined || value === "") return true;
  if (typeof value === "string") return SENTINELS.has(value.trim().toLowerCase());
  if (Array.isArray(value)) return value.length === 0;
  return false;
}

export function formatAnswer(value: unknown): string {
  if (isBlankAnswer(value)) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.map((v) => formatAnswer(v)).join(", ");
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${k}: ${formatAnswer(v)}`)
      .join(" · ");
  }
  return String(value);
}

export function truthy(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value > 0;
  if (typeof value === "string") {
    return ["true", "yes", "y", "1", "high", "interested"].includes(
      value.trim().toLowerCase(),
    );
  }
  return false;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0) return "—";
  // Round once, then split: rounding the remainder on its own renders 119.7s
  // as "1m 60s".
  const total = Math.round(seconds);
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return mins ? `${mins}m ${secs}s` : `${secs}s`;
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diff = Date.now() - then;
  const mins = Math.round(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Calling codes for the countries Hunar can dial. Guessing the code length from
 * a regex mis-splits numbers (+1 202… became "+120 255…"), so only split on a
 * code we actually know and otherwise leave the E.164 string alone.
 */
const CALLING_CODES = ["1", "44", "91", "966"];

export function formatPhone(value: string | null | undefined): string {
  if (!value) return "—";
  if (!value.startsWith("+")) return value;

  const digits = value.slice(1);
  const code = CALLING_CODES.filter((candidate) => digits.startsWith(candidate)).sort(
    (a, b) => b.length - a.length,
  )[0];
  if (!code) return value;

  const rest = digits.slice(code.length);
  if (rest.length < 6) return value;
  // NANP numbers are always 3-3-4; elsewhere split in half rather than
  // pretending to know each country's grouping rules.
  if (code === "1" && rest.length === 10) {
    return `+1 ${rest.slice(0, 3)} ${rest.slice(3, 6)} ${rest.slice(6)}`;
  }
  const pivot = Math.ceil(rest.length / 2);
  return `+${code} ${rest.slice(0, pivot)} ${rest.slice(pivot)}`;
}

/** Statuses that mean "this call is finished, one way or another". */
export const TERMINAL_STATUSES: CallStatus[] = [
  "COMPLETED",
  "NOT_CONNECTED",
  "CANCELLED",
  "FAILED",
];

export const isTerminal = (status: CallStatus) => TERMINAL_STATUSES.includes(status);

/**
 * Keep polling while anything can still change. A COMPLETED call routinely has
 * an empty `result`: Hunar extracts the answers *after* the status flips, so
 * stopping at the terminal status freezes the table on "waiting…" forever.
 */
export const isLive = (calls: Call[]) =>
  calls.some(
    (call) =>
      (call.status !== "PENDING" && !isTerminal(call.status)) ||
      (call.status === "COMPLETED" && !Object.keys(call.result ?? {}).length),
  );

type Tone = "neutral" | "positive" | "warning" | "danger" | "info";

export const CALL_STATUS_TONE: Record<CallStatus, Tone> = {
  PENDING: "neutral",
  NOT_STARTED: "neutral",
  SCHEDULED: "info",
  INITIATED: "info",
  RINGING: "info",
  IN_PROGRESS: "info",
  COMPLETED: "positive",
  NOT_CONNECTED: "warning",
  CANCELLED: "neutral",
  FAILED: "danger",
};

export const CANDIDATE_STATUS_TONE: Record<CandidateStatus, Tone> = {
  SOURCED: "neutral",
  SHORTLISTED: "info",
  REJECTED: "neutral",
  QUEUED: "info",
  CALLING: "info",
  COMPLETED: "positive",
  UNREACHABLE: "warning",
};

export const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-muted text-muted-foreground border-transparent",
  positive:
    "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/50 dark:text-emerald-300 dark:border-emerald-900",
  warning:
    "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/50 dark:text-amber-300 dark:border-amber-900",
  danger:
    "bg-red-50 text-red-700 border-red-200 dark:bg-red-950/50 dark:text-red-300 dark:border-red-900",
  info: "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/50 dark:text-blue-300 dark:border-blue-900",
};

export function scoreTone(score: number): string {
  if (score >= 80) return "text-emerald-600 dark:text-emerald-400";
  if (score >= 60) return "text-amber-600 dark:text-amber-400";
  return "text-muted-foreground";
}

export const titleCase = (value: string) =>
  value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
