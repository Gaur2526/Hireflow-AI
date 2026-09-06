"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useState } from "react";
import { Download, Loader2, PhoneOutgoing, RefreshCw } from "lucide-react";
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
  StatCard,
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

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
              <StatCard label="Calls" value={data.stats.total} />
              <StatCard
                label="Completed"
                value={data.stats.completed}
                tone={data.stats.completed ? "positive" : undefined}
              />
              <StatCard
                label="In flight"
                value={data.stats.in_flight + data.stats.pending}
              />
              <StatCard
                label="Not connected"
                value={data.stats.not_connected + data.stats.failed}
                tone={
                  data.stats.not_connected + data.stats.failed ? "warning" : undefined
                }
              />
              <StatCard
                label="Interested"
                value={data.stats.interested}
                tone={data.stats.interested ? "positive" : undefined}
                hint={`${data.stats.consented} consented`}
              />
              <StatCard
                label="Talk time"
                value={`${data.stats.total_talk_minutes}m`}
                hint={
                  data.stats.avg_duration_seconds
                    ? `avg ${formatDuration(data.stats.avg_duration_seconds)}`
                    : undefined
                }
              />
            </div>

            <Card className="gap-3 py-4">
              <CardContent className="space-y-2 px-4">
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium">
                    {done} of {data.stats.total} calls finished
                  </span>
                  <span className="text-muted-foreground text-xs">
                    updated {formatRelative(data.campaign.updated_at)}
                  </span>
                </div>
                <Progress value={progress} />
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
              <CardHeader>
                <CardTitle className="text-base">Screening answers</CardTitle>
                <p className="text-muted-foreground text-sm">
                  One column per field in the agent&apos;s{" "}
                  <code className="font-mono text-xs">result_schema</code> — generated from
                  this job&apos;s description.
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
