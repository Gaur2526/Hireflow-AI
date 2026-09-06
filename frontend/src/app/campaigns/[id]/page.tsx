"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useState } from "react";
import {
  BarChart3,
  CheckCircle2,
  Clock3,
  Download,
  Heart,
  Loader2,
  PhoneOutgoing,
  PhoneMissed,
  RefreshCw,
  TimerReset,
} from "lucide-react";
import { toast } from "sonner";

import {
  campaignCsvUrl,
  dispatchCampaign,
  getCampaign,
  syncCampaign,
} from "@/lib/api";
import { formatDuration, formatRelative, isLive } from "@/lib/format";
import { useAsync, usePolling } from "@/hooks/use-async";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { ResultsTable } from "@/components/results-table";
import {
  EmptyState,
  ErrorNote,
  PageHeader,
  SkeletonRows,
  WarningList,
} from "@/components/primitives";

export default function CampaignPage() {
  const params = useParams<{ id: string }>();
  const campaignId = params.id;

  const { data, error, loading, reload, setData } = useAsync(
    () => getCampaign(campaignId),
    [campaignId],
  );
  const [syncing, setSyncing] = useState(false);
  const [dispatching, setDispatching] = useState(false);

  const live = data ? isLive(data.calls) : false;

  // While calls are in flight, refresh from the server; stop once everything
  // has reached a terminal state.
  usePolling(
    useCallback(async () => {
      try {
        setData(await getCampaign(campaignId));
      } catch {
        /* transient - the next tick will retry */
      }
    }, [campaignId, setData]),
    { active: live, intervalMs: 5000 },
  );

  async function forceSync() {
    setSyncing(true);
    try {
      setData(await syncCampaign(campaignId));
      toast.success("Synced with Hunar");
    } catch (cause) {
      toast.error("Sync failed", {
        description: cause instanceof Error ? cause.message : String(cause),
      });
    } finally {
      setSyncing(false);
    }
  }

  async function dispatchPending() {
    setDispatching(true);
    try {
      const response = await dispatchCampaign(campaignId);
      toast.success(`${response.dispatched} call(s) placed`);
      await reload();
    } catch (cause) {
      toast.error("Could not place calls", {
        description: cause instanceof Error ? cause.message : String(cause),
      });
    } finally {
      setDispatching(false);
    }
  }

  const stats = data?.stats;
  const done = stats ? stats.completed + stats.not_connected + stats.failed + stats.cancelled : 0;
  const progress = stats?.total ? Math.round((done / stats.total) * 100) : 0;
  const pending = stats?.pending ?? 0;

  return (
    <>
      <PageHeader
        breadcrumb={
          <>
            <Link href="/campaigns" className="hover:underline">
              Campaigns
            </Link>
            {data ? (
              <>
                {" / "}
                <Link href={`/jobs/${data.job_id}`} className="hover:underline">
                  {data.job_title}
                </Link>
              </>
            ) : null}
          </>
        }
        title={data?.campaign.name ?? "Loading…"}
        description={
          data ? (
            <span className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">{data.campaign.status}</Badge>
              {live ? (
                <span className="flex items-center gap-1.5 text-xs text-blue-600 dark:text-blue-400">
                  <span className="relative flex size-2">
                    <span className="absolute inline-flex size-full animate-ping rounded-full bg-blue-400 opacity-75" />
                    <span className="relative inline-flex size-2 rounded-full bg-blue-500" />
                  </span>
                  live — refreshing every 5s
                </span>
              ) : null}
              {data.campaign.hunar_agent_id ? (
                <span className="text-muted-foreground font-mono text-xs">
                  agent {data.campaign.hunar_agent_id.slice(0, 8)}
                </span>
              ) : null}
            </span>
          ) : undefined
        }
        actions={
          <>
            {pending ? (
              <Button onClick={dispatchPending} disabled={dispatching}>
                {dispatching ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <PhoneOutgoing className="size-4" />
                )}
                Place {pending} pending
              </Button>
            ) : null}
            <Button variant="secondary" onClick={forceSync} disabled={syncing}>
              {syncing ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <RefreshCw className="size-4" />
              )}
              Sync
            </Button>
            <Button variant="outline" asChild>
              <a href={campaignCsvUrl(campaignId)}>
                <Download className="size-4" /> CSV
              </a>
            </Button>
          </>
        }
      />

      <div className="space-y-6 p-6">
        {error ? <ErrorNote message={error} /> : null}
        {loading && !data ? <SkeletonRows rows={5} /> : null}

        {data ? (
          <>
            <WarningList warnings={data.warnings} />

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
              <CampaignMetric icon={PhoneOutgoing} label="Calls" value={data.stats.total} tone="blue" />
              <CampaignMetric icon={CheckCircle2} label="Completed" value={data.stats.completed} tone="green" />
              <CampaignMetric icon={TimerReset} label="In flight" value={data.stats.in_flight + data.stats.pending} tone="violet" />
              <CampaignMetric icon={PhoneMissed} label="Not connected" value={data.stats.not_connected + data.stats.failed} tone="amber" />
              <CampaignMetric icon={Heart} label="Interested" value={data.stats.interested} hint={`${data.stats.consented} consented`} tone="rose" />
              <CampaignMetric icon={Clock3} label="Talk time" value={`${data.stats.total_talk_minutes}m`} hint={data.stats.avg_duration_seconds ? `avg ${formatDuration(data.stats.avg_duration_seconds)}` : undefined} tone="cyan" />
            </div>

            <Card className="relative gap-3 overflow-hidden py-5">
              <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-primary via-cyan-400 to-emerald-400" />
              <CardContent className="space-y-3 px-5">
                <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                  <div>
                    <div className="eyebrow text-primary">Campaign progress</div>
                    <span className="mt-1 block text-base font-semibold">{done} of {data.stats.total} calls finished</span>
                  </div>
                  <span className="rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground">
                    Updated {formatRelative(data.campaign.updated_at)}
                  </span>
                </div>
                <Progress value={progress} className="h-2" />
                {data.stats.do_not_contact ? (
                  <p className="text-xs text-amber-600 dark:text-amber-400">
                    {data.stats.do_not_contact} candidate
                    {data.stats.do_not_contact === 1 ? "" : "s"} asked not to be contacted
                    again — suppress them from future campaigns.
                  </p>
                ) : null}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="border-b border-border/70 pb-4">
                <div className="flex items-center gap-3">
                  <span className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-blue-600 to-cyan-500 text-white shadow-lg shadow-blue-500/20"><BarChart3 className="size-4" /></span>
                  <div>
                    <div className="eyebrow text-primary">Screening intelligence</div>
                    <CardTitle className="mt-0.5 text-lg">Candidate answers</CardTitle>
                  </div>
                </div>
                <p className="text-muted-foreground text-sm">
                  Structured responses extracted from the voice conversation.
                </p>
              </CardHeader>
              <CardContent>
                {data.calls.length ? (
                  <ResultsTable calls={data.calls} columns={data.answer_columns} />
                ) : (
                  <EmptyState
                    title="No calls in this campaign"
                    description="Every selected candidate was skipped — check the warnings above."
                  />
                )}
              </CardContent>
            </Card>
          </>
        ) : null}
      </div>
    </>
  );
}

function CampaignMetric({
  icon: Icon,
  label,
  value,
  hint,
  tone,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone: "blue" | "green" | "violet" | "amber" | "rose" | "cyan";
}) {
  const tones = {
    blue: "bg-blue-50 text-blue-600",
    green: "bg-emerald-50 text-emerald-600",
    violet: "bg-violet-50 text-violet-600",
    amber: "bg-amber-50 text-amber-600",
    rose: "bg-rose-50 text-rose-600",
    cyan: "bg-cyan-50 text-cyan-600",
  };

  return (
    <Card className="gap-0 py-4">
      <CardContent className="px-4">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] font-semibold tracking-[0.08em] text-muted-foreground uppercase">{label}</span>
          <span className={`flex size-8 items-center justify-center rounded-xl ${tones[tone]}`}><Icon className="size-4" /></span>
        </div>
        <div className="mt-3 text-3xl font-semibold tracking-tight tabular-nums">{value}</div>
        <div className="mt-1 h-4 text-xs text-muted-foreground">{hint}</div>
      </CardContent>
    </Card>
  );
}
