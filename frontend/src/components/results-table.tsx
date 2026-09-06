"use client";

import { useState } from "react";
import { ExternalLink, Play } from "lucide-react";

import { cn } from "@/lib/utils";
import {
  formatAnswer,
  formatDuration,
  isBlankAnswer,
  isTerminal,
  truthy,
} from "@/lib/format";
import type { AnswerColumn, Call } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CallDetailSheet } from "@/components/call-detail-sheet";
import { CallStatusBadge, FitScore } from "@/components/primitives";

/**
 * One row per call, one column per `result_schema` key.
 *
 * The columns are not hard-coded: they come from the schema the job description
 * generated, so a different JD produces a different set of answer columns.
 */
export function ResultsTable({
  calls,
  columns,
}: {
  calls: Call[];
  columns: AnswerColumn[];
}) {
  // Hold the id, not the row: `calls` is replaced on every poll, so a captured
  // object would freeze the sheet on the snapshot taken when it was opened.
  const [activeId, setActiveId] = useState<string | null>(null);
  const active = calls.find((call) => call.id === activeId) ?? null;

  // Keep the table readable: the narrative fields live in the detail sheet.
  const inline = columns.filter(
    (column) => !["screening_summary"].includes(column.key),
  );

  return (
    <>
      <div className="overflow-x-auto rounded-2xl border border-border/80 bg-card shadow-[0_8px_24px_oklch(0.2_0.04_258/0.04)]">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="sticky left-0 z-10 min-w-[230px] bg-muted">
                Candidate
              </TableHead>
              <TableHead className="w-32">Call</TableHead>
              <TableHead className="w-20 text-right">Length</TableHead>
              {inline.map((column) => (
                <TableHead key={column.key} className="min-w-[140px] whitespace-nowrap">
                  <span title={column.description}>{column.label}</span>
                </TableHead>
              ))}
              <TableHead className="w-24" />
            </TableRow>
          </TableHeader>

          <TableBody>
            {calls.map((call) => {
              const answered = Object.keys(call.result ?? {}).length > 0;
              // A finished call that produced nothing never will - say "—"
              // rather than leaving the row looking like it is still working.
              const pending = !answered && !isTerminal(call.status);
              return (
                <TableRow key={call.id}>
                  <TableCell className="sticky left-0 z-10 bg-card">
                    <div className="flex items-center gap-2">
                      <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-blue-100 to-cyan-100 text-xs font-bold text-primary">
                        {call.candidate_name.slice(0, 1).toUpperCase()}
                      </span>
                      <div className="min-w-0">
                        <div className="flex items-center gap-1 truncate text-sm font-semibold">
                          {call.candidate_name}
                          {call.candidate_linkedin ? (
                            <a
                              href={call.candidate_linkedin}
                              target="_blank"
                              rel="noreferrer noopener"
                              className="text-muted-foreground hover:text-foreground"
                              aria-label={`${call.candidate_name} on LinkedIn`}
                            >
                              <ExternalLink className="size-3" />
                            </a>
                          ) : null}
                        </div>
                        <div className="text-muted-foreground truncate text-xs">
                          {call.candidate_title ?? "—"}
                        </div>
                      </div>
                      <FitScore score={call.candidate_fit_score} className="ml-auto" />
                    </div>
                  </TableCell>

                  <TableCell>
                    <CallStatusBadge status={call.status} />
                    {call.dialed_redirected ? (
                      <div className="text-muted-foreground mt-0.5 text-[10px]">
                        redirected
                      </div>
                    ) : null}
                  </TableCell>

                  <TableCell className="text-right font-mono text-xs tabular-nums">
                    {formatDuration(call.duration_seconds)}
                  </TableCell>

                  {inline.map((column) => (
                    <TableCell key={column.key} className="max-w-[220px] text-sm">
                      <AnswerCell
                        value={call.result?.[column.key]}
                        type={column.type}
                        pending={pending}
                      />
                    </TableCell>
                  ))}

                  <TableCell className="text-right">
                    <Button variant="ghost" size="sm" onClick={() => setActiveId(call.id)}>
                      Details
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <CallDetailSheet
        call={active}
        columns={columns}
        onOpenChange={(open) => !open && setActiveId(null)}
      />
    </>
  );
}

function AnswerCell({
  value,
  type,
  pending,
}: {
  value: unknown;
  type: AnswerColumn["type"];
  pending: boolean;
}) {
  if (pending) {
    return <span className="text-muted-foreground/60 text-xs">waiting…</span>;
  }
  if (isBlankAnswer(value)) {
    return <span className="text-muted-foreground">—</span>;
  }
  if (type === "boolean") {
    const yes = truthy(value);
    return (
      <span
        className={cn(
          "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
          yes
            ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300"
            : "bg-muted text-muted-foreground",
        )}
      >
        {yes ? "Yes" : "No"}
      </span>
    );
  }
  if (type === "number") {
    return <span className="font-mono tabular-nums">{formatAnswer(value)}</span>;
  }
  const text = formatAnswer(value);
  return (
    <span className="line-clamp-2 leading-snug" title={text}>
      {text}
    </span>
  );
}

export function RecordingButton({ url }: { url: string }) {
  return (
    <Button variant="outline" size="sm" asChild>
      <a href={url} target="_blank" rel="noreferrer noopener">
        <Play className="size-3" /> Recording
      </a>
    </Button>
  );
}
