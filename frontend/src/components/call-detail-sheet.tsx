"use client";

import { AudioLines, PhoneCall } from "lucide-react";

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
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
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

              {call.recording_url ? (
                <div className="space-y-2">
                  <Separator />
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <AudioLines className="size-4" /> Recording
                  </div>
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
                </div>
              ) : null}

              <Separator />

              <div>
                <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                  <PhoneCall className="size-4" /> What the agent got
                </div>
                {Object.keys(call.result ?? {}).length ? (
                  <dl className="space-y-3">
                    {columns.map((column) => {
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
                    {extraKeys(call, columns).map((key) => (
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
