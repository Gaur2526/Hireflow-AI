"use client";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  CALL_STATUS_TONE,
  CANDIDATE_STATUS_TONE,
  TONE_CLASSES,
  scoreTone,
  titleCase,
} from "@/lib/format";
import type { CallStatus, CandidateStatus } from "@/lib/types";

export function PageHeader({
  title,
  description,
  actions,
  breadcrumb,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  breadcrumb?: React.ReactNode;
}) {
  return (
    <div className="border-b border-border/80 bg-background/70 px-6 py-5 backdrop-blur-sm">
      {breadcrumb ? (
        <div className="text-muted-foreground mb-1.5 text-xs">{breadcrumb}</div>
      ) : null}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
          {description ? (
            <p className="text-muted-foreground mt-1 max-w-3xl text-sm">{description}</p>
          ) : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}

export function CallStatusBadge({ status }: { status: CallStatus }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        TONE_CLASSES[CALL_STATUS_TONE[status] ?? "neutral"],
      )}
    >
      {titleCase(status)}
    </span>
  );
}

export function CandidateStatusBadge({ status }: { status: CandidateStatus }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        TONE_CLASSES[CANDIDATE_STATUS_TONE[status] ?? "neutral"],
      )}
    >
      {titleCase(status)}
    </span>
  );
}

export function FitScore({ score, className }: { score: number; className?: string }) {
  return (
    <span className={cn("font-mono text-sm font-semibold tabular-nums", scoreTone(score), className)}>
      {score.toFixed(0)}
    </span>
  );
}

export function StatCard({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: "positive" | "warning" | "danger";
}) {
  return (
    <Card className="workspace-card gap-0 py-4">
      <CardContent className="px-4">
        <div className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
          {label}
        </div>
        <div
          className={cn(
            "mt-1.5 text-2xl font-semibold tracking-tight tabular-nums",
            tone === "positive" && "text-emerald-600 dark:text-emerald-400",
            tone === "warning" && "text-amber-600 dark:text-amber-400",
            tone === "danger" && "text-red-600 dark:text-red-400",
          )}
        >
          {value}
        </div>
        {hint ? <div className="text-muted-foreground mt-0.5 text-xs">{hint}</div> : null}
      </CardContent>
    </Card>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon?: React.ComponentType<{ className?: string }>;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card/60 px-6 py-14 text-center">
      {Icon ? <Icon className="mb-3 size-8 text-primary/60" /> : null}
      <p className="font-medium">{title}</p>
      {description ? (
        <p className="text-muted-foreground mt-1 max-w-md text-sm">{description}</p>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">
      {message}
    </div>
  );
}

export function WarningList({ warnings }: { warnings: string[] }) {
  if (!warnings.length) return null;
  return (
    <ul className="space-y-1 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
      {warnings.map((warning, index) => (
        <li key={index} className="flex gap-1.5">
          <span aria-hidden>•</span>
          <span>{warning}</span>
        </li>
      ))}
    </ul>
  );
}

export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-11 w-full" />
      ))}
    </div>
  );
}

export function Chips({ items, max = 8 }: { items: string[]; max?: number }) {
  if (!items.length) return <span className="text-muted-foreground text-sm">—</span>;
  const shown = items.slice(0, max);
  return (
    <div className="flex flex-wrap gap-1">
      {shown.map((item) => (
        <Badge key={item} variant="secondary" className="font-normal">
          {item}
        </Badge>
      ))}
      {items.length > max ? (
        <Badge variant="outline" className="font-normal">
          +{items.length - max}
        </Badge>
      ) : null}
    </div>
  );
}
