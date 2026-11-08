"use client";

import { AudioLines, ClipboardCheck, MessageSquareText, PhoneCall } from "lucide-react";

import {
  formatAnswer,
  formatDateTime,
  formatDuration,
  formatPhone,
  isBlankAnswer,
} from "@/lib/format";
import type { AnswerColumn, Call } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { CallStatusBadge, FitScore } from "@/components/primitives";

const HIGHLIGHT_KEYS = new Set([
  "notice_period",
  "expected_ctc",
  "expected_compensation",
  "expected_salary",
  "interested",
  "is_interested",
  "open_to_opportunity",
  "interest_level",
  "screening_summary",
  "summary",
]);

/** Everything one call produced: metadata, the recording, and every answer. */
export function CallDetailSheet({
  call,
  columns,
  onOpenChange,
}: {
  call: Call | null;
  columns: AnswerColumn[];
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Sheet open={Boolean(call)} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        {call ? (
          <>
            <SheetHeader>
              <SheetTitle className="flex items-center gap-2">
                {call.candidate_name}
                <FitScore score={call.candidate_fit_score} />
              </SheetTitle>
              <SheetDescription>
                {[call.candidate_title, call.candidate_company]
                  .filter(Boolean)
                  .join(" · ") || "—"}
              </SheetDescription>
            </SheetHeader>

            <div className="space-y-5 px-4 pb-8">
              <div className="flex flex-wrap items-center gap-2">
                <CallStatusBadge status={call.status} />
                {call.answered_by ? (
                  <Badge variant="secondary" className="font-normal">
                    Answered by {call.answered_by.toLowerCase()}
                  </Badge>
                ) : null}
                {call.engagement_status ? (
                  <Badge variant="secondary" className="font-normal">
                    {call.engagement_status.toLowerCase()}
                  </Badge>
                ) : null}
                {call.dialed_redirected ? (
                  <Badge variant="outline" className="font-normal">
                    demo redirect
                  </Badge>
                ) : null}
              </div>

              {call.error ? (
                <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">
                  {call.error}
                </p>
              ) : null}

              <section className="rounded-2xl border border-border/80 bg-gradient-to-br from-card via-card to-teal-50/70 p-4 dark:to-teal-950/20">
                <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
                  <ClipboardCheck className="size-4 text-primary" /> Screening highlights
                </div>
                <div className="grid gap-2 sm:grid-cols-3">
                  <Highlight label="Notice period" value={answer(call.result, ["notice_period"])} />
                  <Highlight label="Expected CTC" value={answer(call.result, ["expected_ctc", "expected_compensation", "expected_salary"])} />
                  <Highlight label="Interested" value={answer(call.result, ["interested", "is_interested", "open_to_opportunity", "interest_level"])} />
                </div>
                <div className="mt-2 rounded-xl bg-background/80 p-3">
                  <div className="text-muted-foreground text-[10px] font-semibold tracking-[0.12em] uppercase">Call summary</div>
                  <p className="mt-1 text-sm leading-6">
                    {formatAnswer(answer(call.result, ["screening_summary", "summary"]))}
                  </p>
                </div>
              </section>

              <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-sm">
                <Meta label="Dialled" value={formatPhone(call.dialed_number)} mono />
                <Meta label="Duration" value={formatDuration(call.duration_seconds)} />
                <Meta
                  label="Candidate spoke"
                  value={formatDuration(call.user_speech_duration)}
                />
                <Meta label="Retries" value={String(call.retry_count)} />
                <Meta label="Started" value={formatDateTime(call.started_at)} />
                <Meta label="Ended" value={formatDateTime(call.ended_at)} />
                <Meta
                  label="Last synced"
                  value={`${formatDateTime(call.last_synced_at)}${
                    call.sync_source ? ` (${call.sync_source})` : ""
                  }`}
                />
                <Meta label="Hunar call id" value={call.hunar_call_id ?? "—"} mono />
              </dl>

              <section className="space-y-3 rounded-2xl border border-border/80 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2 text-sm font-semibold">
                      <AudioLines className="size-4 text-primary" /> Call recording
                    </div>
                    <p className="text-muted-foreground mt-1 text-xs">{call.recording_url ? "Replay the full screening conversation." : "No recording is available for this call yet."}</p>
                  </div>
                  {call.duration_seconds ? <Badge variant="secondary">{formatDuration(call.duration_seconds)}</Badge> : null}
                </div>
                {call.recording_url ? (
                  <>
                  <audio controls preload="none" src={call.recording_url} className="w-full">
                    Your browser cannot play this recording.
                  </audio>
                  <a
                    href={call.recording_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="text-muted-foreground text-xs underline"
                  >
                    Open in a new tab
                  </a>
                  </>
                ) : null}
              </section>

              <section className="rounded-2xl border border-border/80 p-4">
                <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
                  <MessageSquareText className="size-4 text-primary" /> Conversation transcript
                </div>
                {call.transcript?.length ? (
                  <ol className="space-y-0">
                    {call.transcript.map((line, index) => (
                      <li key={`${line.timestamp ?? index}-${index}`} className="relative grid grid-cols-[56px_1fr] gap-3 pb-4 last:pb-0">
                        <span className="text-muted-foreground pt-0.5 text-right font-mono text-[10px]">{transcriptTime(line.timestamp)}</span>
                        <span className="absolute top-1.5 left-[62px] size-1.5 rounded-full bg-primary ring-4 ring-primary/10" />
                        <div className="border-l border-border pl-4">
                          <div className="text-muted-foreground text-[10px] font-semibold tracking-wide uppercase">{line.speaker}</div>
                          <p className="mt-1 text-sm leading-6">{line.text}</p>
                        </div>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="text-muted-foreground rounded-xl bg-muted/50 px-3 py-4 text-sm">
                    A transcript wasn&apos;t provided for this call. The structured answers and summary are shown above.
                  </p>
                )}
              </section>

              <div>
                <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                  <PhoneCall className="size-4" /> What the agent got
                </div>
                {Object.keys(call.result ?? {}).length ? (
                  <dl className="space-y-3">
                    {columns.filter((column) => !HIGHLIGHT_KEYS.has(column.key)).map((column) => {
                      const value = call.result?.[column.key];
                      return (
                        <div key={column.key}>
                          <dt className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                            {column.label}
                          </dt>
                          <dd
                            className={
                              isBlankAnswer(value)
                                ? "text-muted-foreground text-sm"
                                : "text-sm"
                            }
                          >
                            {formatAnswer(value)}
                          </dd>
                        </div>
                      );
                    })}
                    {extraKeys(call, columns).filter((key) => !HIGHLIGHT_KEYS.has(key)).map((key) => (
                      <div key={key}>
                        <dt className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                          {key.replace(/_/g, " ")}
                        </dt>
                        <dd className="text-sm">{formatAnswer(call.result[key])}</dd>
                      </div>
                    ))}
                  </dl>
                ) : (
                  <p className="text-muted-foreground text-sm">
                    No answers yet. Hunar extracts them shortly after the call ends.
                  </p>
                )}
              </div>

              {Object.keys(call.custom_data ?? {}).length ? (
                <>
                  <Separator />
                  <div>
                    <div className="mb-2 text-sm font-medium">Context sent to the agent</div>
                    <dl className="space-y-1.5 text-xs">
                      {Object.entries(call.custom_data).map(([key, value]) => (
                        <div key={key}>
                          <dt className="text-muted-foreground font-mono">{key}</dt>
                          <dd>{formatAnswer(value)}</dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                </>
              ) : null}
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

/** Answers Hunar returned that the schema did not declare — show them anyway. */
function extraKeys(call: Call, columns: AnswerColumn[]): string[] {
  const known = new Set(columns.map((column) => column.key));
  return Object.keys(call.result ?? {}).filter((key) => !known.has(key));
}

function answer(result: Record<string, unknown>, keys: string[]): unknown {
  const key = keys.find((candidate) => result[candidate] !== undefined && result[candidate] !== null);
  return key ? result[key] : null;
}

function transcriptTime(value: string | null): string {
  if (!value) return "—";
  if (/^\d{1,2}:\d{2}(:\d{2})?$/.test(value)) return value;
  const seconds = Number(value);
  if (Number.isFinite(seconds)) return seconds === 0 ? "0s" : formatDuration(seconds);
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : formatDateTime(value);
}

function Highlight({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-xl border border-border/60 bg-background/80 p-3">
      <div className="text-muted-foreground text-[10px] font-semibold tracking-[0.1em] uppercase">{label}</div>
      <div className="mt-1.5 text-sm font-medium">{isBlankAnswer(value) ? "Not captured" : formatAnswer(value)}</div>
    </div>
  );
}

function Meta({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className={mono ? "font-mono text-xs break-all" : "text-sm"}>{value}</dd>
    </div>
  );
}
