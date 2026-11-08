"use client";

import Link from "next/link";
import { ArrowUpRight, PhoneCall, Radio } from "lucide-react";

import { listCampaigns } from "@/lib/api";
import { formatDuration, formatRelative } from "@/lib/format";
import { useAsync } from "@/hooks/use-async";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  EmptyState,
  ErrorNote,
  PageHeader,
  SkeletonRows,
} from "@/components/primitives";

export default function CampaignsPage() {
  const { data, error, loading } = useAsync(() => listCampaigns());

  return (
    <>
      <PageHeader
        title="Campaigns"
        description="Each campaign is one Hunar voice agent calling a shortlist and bringing back structured answers."
      />

      <div className="space-y-4 p-6">
        {error ? <ErrorNote message={error} /> : null}
        {loading && !data ? <SkeletonRows /> : null}

        {data && data.length === 0 ? (
          <EmptyState
            icon={PhoneCall}
            title="No campaigns yet"
            description="Open a job, shortlist a few candidates, and launch voice screening."
          />
        ) : null}

        {data && data.length > 0 ? (
          <div className="rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Campaign</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead className="min-w-64">Candidates · outcome</TableHead>
                  <TableHead className="w-48">Progress</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead>Updated</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((campaign) => {
                  const done =
                    campaign.stats.completed +
                    campaign.stats.not_connected +
                    campaign.stats.failed +
                    campaign.stats.cancelled;
                  const pct = campaign.stats.total
                    ? Math.round((done / campaign.stats.total) * 100)
                    : 0;
                  return (
                    <TableRow key={campaign.id}>
                      <TableCell className="font-medium">
                        <Link
                          href={`/campaigns/${campaign.id}`}
                          className="group flex items-center gap-2 hover:text-primary"
                        >
                          <span className="truncate">{campaign.name}</span>
                          <ArrowUpRight className="size-3.5 shrink-0 opacity-0 transition group-hover:opacity-100" />
                        </Link>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        <Link href={`/jobs/${campaign.job_id}`} className="hover:underline">
                          {campaign.job_title || "—"}
                        </Link>
                      </TableCell>
                      <TableCell className="py-3">
                        <div className="space-y-2">
                          {campaign.call_previews.length ? campaign.call_previews.map((call) => (
                            <div key={call.call_id} className="flex min-w-64 items-center justify-between gap-3">
                              <div className="min-w-0">
                                <div className="truncate text-sm font-medium">{call.candidate_name}</div>
                                <div className="text-muted-foreground text-xs">{formatDuration(call.duration_seconds)}</div>
                              </div>
                              <OutcomeBadge outcome={call.outcome} />
                            </div>
                          )) : <span className="text-muted-foreground text-xs">No candidates in this campaign</span>}
                          {campaign.stats.total > campaign.call_previews.length ? (
                            <div className="text-muted-foreground text-[11px]">+{campaign.stats.total - campaign.call_previews.length} more candidates</div>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Progress value={pct} className="h-1.5" />
                          <span className="text-muted-foreground w-14 shrink-0 text-right text-xs tabular-nums">
                            {done}/{campaign.stats.total}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          {campaign.status === "RUNNING" ? (
                            <span className="flex items-center gap-1.5 text-xs font-medium text-teal-700 dark:text-teal-300">
                              <Radio className="size-3.5 animate-pulse" /> Live
                            </span>
                          ) : (
                            <Badge variant="secondary">{campaign.status.replaceAll("_", " ")}</Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-sm">
                        {formatRelative(campaign.updated_at)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        ) : null}
      </div>
    </>
  );
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const tone = outcome === "Interested"
    ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-300"
    : outcome === "Not interested"
      ? "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
      : outcome === "No answer" || outcome === "Voicemail"
        ? "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-300"
        : outcome === "Failed"
          ? "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/50 dark:text-red-300"
          : "border-border bg-muted text-muted-foreground";
  return <Badge variant="outline" className={`shrink-0 font-medium ${tone}`}>{outcome}</Badge>;
}
