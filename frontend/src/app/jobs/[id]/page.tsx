"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import {
  Database,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Sparkles,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import {
  getConfig,
  getJob,
  getScreeningPlan,
  listCampaigns,
  listCandidates,
  searchCandidates,
  setShortlist,
} from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type { Candidate } from "@/lib/types";
import { useAsync } from "@/hooks/use-async";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CampaignLauncher } from "@/components/campaign-launcher";
import { CandidateTable } from "@/components/candidate-table";
import { ScreeningPlanCard } from "@/components/screening-plan-card";
import {
  Chips,
  EmptyState,
  ErrorNote,
  PageHeader,
  SkeletonRows,
  StatCard,
  WarningList,
} from "@/components/primitives";

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const jobId = params.id;

  const job = useAsync(() => getJob(jobId), [jobId]);
  const config = useAsync(getConfig);
  const plan = useAsync(() => getScreeningPlan(jobId), [jobId]);
  const campaigns = useAsync(() => listCampaigns(jobId), [jobId]);
  const candidates = useAsync(() => listCandidates(jobId), [jobId]);

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [searching, setSearching] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [limit, setLimit] = useState(20);
  const [requirePhone, setRequirePhone] = useState(false);
  const [minScore, setMinScore] = useState(0);

  const rows = useMemo(() => {
    const all = candidates.data ?? [];
    return all.filter((c) => c.fit_score >= minScore);
  }, [candidates.data, minScore]);

  // Only what is on screen counts as selected: raising the min fit score must
  // not leave invisible candidates queued for a real phone call.
  const selectedIds = useMemo(
    () => rows.filter((c) => selected.has(c.id)).map((c) => c.id),
    [rows, selected],
  );

  const toggle = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleAll = useCallback((ids: string[], value: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => (value ? next.add(id) : next.delete(id)));
      return next;
    });
  }, []);

  const onCandidateUpdated = useCallback(
    (updated: Candidate) => {
      candidates.setData(
        (candidates.data ?? []).map((c) => (c.id === updated.id ? updated : c)),
      );
    },
    [candidates],
  );

  async function runSearch() {
    setSearching(true);
    setWarnings([]);
    try {
      const response = await searchCandidates(jobId, {
        limit,
        require_phone: requirePhone,
      });
      candidates.setData(response.candidates);
      setWarnings(response.warnings);
      toast.success(
        `${response.run.new_candidates} new candidate${
          response.run.new_candidates === 1 ? "" : "s"
        } from ${response.provider_label}`,
        {
          description: `${response.run.returned} returned in ${response.run.latency_ms ?? 0}ms${
            response.run.total_available
              ? ` · ${response.run.total_available.toLocaleString()} matched upstream`
              : ""
          }`,
        },
      );
    } catch (cause) {
      toast.error("Search failed", {
        description: cause instanceof Error ? cause.message : String(cause),
      });
    } finally {
      setSearching(false);
    }
  }

  async function shortlistSelected() {
    if (!selectedIds.length) return;
    try {
      const updated = await setShortlist(jobId, selectedIds);
      const byId = new Map(updated.map((c) => [c.id, c]));
      candidates.setData(
        (candidates.data ?? []).map((c) => byId.get(c.id) ?? c),
      );
      toast.success(`${updated.length} shortlisted`);
    } catch (cause) {
      toast.error("Could not shortlist", {
        description: cause instanceof Error ? cause.message : String(cause),
      });
    }
  }

  const criteria = job.data?.criteria;
  const callable = rows.filter((c) => c.phone).length;

  return (
    <>
      <PageHeader
        breadcrumb={
          <Link href="/jobs" className="hover:underline">
            Jobs
          </Link>
        }
        title={job.data?.title ?? "Loading…"}
        description={
          job.data
            ? [job.data.company, job.data.location].filter(Boolean).join(" · ") || undefined
            : undefined
        }
        actions={
          <>
            {job.data?.parsed_by === "llm" ? (
              <Badge variant="secondary" className="gap-1 font-normal">
                <Sparkles className="size-3" /> Parsed by Claude
              </Badge>
            ) : null}
            {job.data ? (
              <CampaignLauncher
                job={job.data}
                config={config.data}
                selectedIds={selectedIds}
              />
            ) : null}
          </>
        }
      />

      <div className="space-y-6 p-6">
        {job.error ? <ErrorNote message={job.error} /> : null}

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Sourced" value={candidates.data?.length ?? "—"} />
          <StatCard
            label="Callable"
            value={callable}
            hint={
              callable < (candidates.data?.length ?? 0)
                ? `${(candidates.data?.length ?? 0) - callable} without a number`
                : undefined
            }
          />
          <StatCard label="Selected" value={selectedIds.length} />
          <StatCard label="Campaigns" value={campaigns.data?.length ?? 0} />
        </div>

        <Tabs defaultValue="candidates">
          <TabsList>
            <TabsTrigger value="candidates">Candidates</TabsTrigger>
            <TabsTrigger value="criteria">Criteria</TabsTrigger>
            <TabsTrigger value="script">Screening script</TabsTrigger>
            <TabsTrigger value="campaigns">Campaigns</TabsTrigger>
          </TabsList>

          <TabsContent value="candidates" className="space-y-4">
            {!candidates.loading && (candidates.data?.length ?? 0) === 0 ? (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-cyan-200 bg-cyan-50/70 px-4 py-3 text-sm text-cyan-950">
                <div className="flex items-center gap-2"><span className="flex size-6 items-center justify-center rounded-full bg-cyan-600 text-white"><Play className="size-3 fill-current" /></span><span><strong>Demo step 2 of 3</strong> · Source synthetic candidates for this role.</span></div>
                <span className="text-xs text-cyan-800">The mock provider uses fictional records only.</span>
              </div>
            ) : null}
            <Card>
              <CardContent className="flex flex-wrap items-end gap-4">
                <div className="space-y-1.5">
                  <Label htmlFor="limit">How many</Label>
                  <Input
                    id="limit"
                    type="number"
                    min={1}
                    max={100}
                    value={limit}
                    onChange={(event) => setLimit(Number(event.target.value))}
                    className="w-24"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="min-score">Min fit score</Label>
                  <Input
                    id="min-score"
                    type="number"
                    min={0}
                    max={100}
                    value={minScore}
                    onChange={(event) => setMinScore(Number(event.target.value))}
                    className="w-24"
                  />
                </div>
                <label className="flex items-center gap-2 pb-2 text-sm">
                  <Checkbox
                    checked={requirePhone}
                    onCheckedChange={(value) => setRequirePhone(Boolean(value))}
                  />
                  Only with a phone number
                </label>

                <div className="ml-auto flex items-center gap-2 pb-0.5">
                  <Badge variant="outline" className="gap-1 font-normal">
                    <Database className="size-3" />
                    {config.data?.providers.find((p) => p.active)?.label ?? "…"}
                  </Badge>
                  <Button
                    variant="secondary"
                    onClick={shortlistSelected}
                    disabled={!selectedIds.length}
                  >
                    Shortlist {selectedIds.length || ""}
                  </Button>
                  <Button onClick={runSearch} disabled={searching}>
                    {searching ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <Search className="size-4" />
                    )}
                    Source candidates
                  </Button>
                </div>
              </CardContent>
            </Card>

            <WarningList warnings={warnings} />
            {candidates.error ? <ErrorNote message={candidates.error} /> : null}

            {candidates.loading && !candidates.data ? <SkeletonRows rows={5} /> : null}

            {candidates.data && !candidates.error && rows.length === 0 ? (
              <EmptyState
                icon={Users}
                title={candidates.data.length ? "No candidates above that score" : "No candidates yet"}
                description={
                  candidates.data.length
                    ? "Lower the minimum fit score to see the rest."
                    : "Run a search to pull people matching this job's criteria."
                }
                action={
                  candidates.data.length ? null : (
                    <Button onClick={runSearch} disabled={searching}>
                      <Search className="size-4" /> Source candidates
                    </Button>
                  )
                }
              />
            ) : null}

            {rows.length ? (
              <CandidateTable
                candidates={rows}
                selected={selected}
                onToggle={toggle}
                onToggleAll={toggleAll}
                onCandidateUpdated={onCandidateUpdated}
              />
            ) : null}
          </TabsContent>

          <TabsContent value="criteria">
            {criteria ? (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Extracted criteria</CardTitle>
                  <p className="text-muted-foreground text-sm">{criteria.summary}</p>
                </CardHeader>
                <CardContent className="grid gap-4 sm:grid-cols-2">
                  <Detail label="Titles searched">
                    <Chips items={criteria.titles} />
                  </Detail>
                  <Detail label="Seniority">
                    <Chips items={criteria.seniority} />
                  </Detail>
                  <Detail label="Must have">
                    <Chips items={criteria.must_have_skills} max={14} />
                  </Detail>
                  <Detail label="Nice to have">
                    <Chips items={criteria.nice_to_have_skills} max={14} />
                  </Detail>
                  <Detail label="Experience">
                    {criteria.min_years
                      ? `${criteria.min_years}${criteria.max_years ? `–${criteria.max_years}` : "+"} years`
                      : "Not stated"}
                  </Detail>
                  <Detail label="Locations">
                    <Chips items={criteria.locations} />
                  </Detail>
                  <Detail label="Work mode">{criteria.work_mode ?? "Not stated"}</Detail>
                  <Detail label="Compensation">{criteria.compensation ?? "Not stated"}</Detail>
                  <div className="sm:col-span-2">
                    <Separator className="my-2" />
                    <Detail label="Original description">
                      <pre className="bg-muted/50 max-h-72 overflow-auto rounded-md p-3 font-mono text-[11px] whitespace-pre-wrap">
                        {job.data?.description}
                      </pre>
                    </Detail>
                  </div>
                </CardContent>
              </Card>
            ) : (
              <SkeletonRows rows={4} />
            )}
          </TabsContent>

          <TabsContent value="script">
            {plan.error ? <ErrorNote message={plan.error} /> : null}
            {plan.data ? <ScreeningPlanCard plan={plan.data} /> : <SkeletonRows rows={4} />}
          </TabsContent>

          <TabsContent value="campaigns" className="space-y-3">
            {campaigns.error ? <ErrorNote message={campaigns.error} /> : null}
            {campaigns.data?.length ? (
              <div className="divide-y rounded-lg border">
                {campaigns.data.map((campaign) => (
                  <Link
                    key={campaign.id}
                    href={`/campaigns/${campaign.id}`}
                    className="hover:bg-secondary/50 flex items-center justify-between gap-4 px-4 py-3 transition-colors"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">{campaign.name}</div>
                      <div className="text-muted-foreground text-xs">
                        {campaign.stats.completed}/{campaign.stats.total} done ·{" "}
                        {formatRelative(campaign.created_at)}
                      </div>
                    </div>
                    <Badge variant="secondary">{campaign.status}</Badge>
                  </Link>
                ))}
              </div>
            ) : campaigns.error ? null : (
              <EmptyState
                icon={RefreshCw}
                title="No campaigns for this job"
                description="Select candidates on the Candidates tab, then launch voice screening."
              />
            )}
          </TabsContent>
        </Tabs>
      </div>
    </>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
        {label}
      </div>
      <div className="text-sm">{children}</div>
    </div>
  );
}
