"use client";

import Link from "next/link";
import {
  ArrowRight,
  ArrowUpRight,
  AlertTriangle,
  Briefcase,
  Check,
  CheckCircle2,
  Database,
  Heart,
  PhoneCall,
  Play,
  Plus,
  Users,
  Waves,
} from "lucide-react";

import { getConfig, getOverview } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { useAsync } from "@/hooks/use-async";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { DashboardOverview } from "@/lib/types";
import {
  EmptyState,
  ErrorNote,
  PageHeader,
  SkeletonRows,
} from "@/components/primitives";

export default function DashboardPage() {
  const { data, error, loading } = useAsync(getOverview);
  const config = useAsync(getConfig);

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Your recruiting command centre for sourcing, shortlisting, and structured voice screening."
        actions={
          <Button asChild>
            <Link href="/jobs/new">
              <Plus className="size-4" /> New job
            </Link>
          </Button>
        }
      />

      <div className="space-y-6 p-6">
        {error ? <ErrorNote message={error} /> : null}
        {loading && !data ? <SkeletonRows rows={3} /> : null}

        {data ? (
          <>
            {data.totals.jobs === 0 ? <DemoJourney /> : null}

            <div className="grid gap-4 xl:grid-cols-[minmax(0,1.8fr)_minmax(280px,0.8fr)]">
              <Card className="workspace-card overflow-hidden">
                <CardHeader className="border-b border-border/70 bg-gradient-to-r from-teal-50/70 to-cyan-50/60 dark:from-teal-950/25 dark:to-cyan-950/10">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="eyebrow text-primary">Hiring pipeline</div>
                      <CardTitle className="mt-1 text-lg">Your funnel at a glance</CardTitle>
                    </div>
                    <Badge variant="outline" className="rounded-full bg-background/70">
                      {data.totals.jobs} {data.totals.jobs === 1 ? "job" : "jobs"}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-5 xl:gap-2">
                  <FunnelStage icon={Users} label="Sourced" value={data.totals.candidates} previous={null} tint="blue" />
                  <FunnelStage icon={Check} label="Shortlisted" value={data.totals.shortlisted} previous={data.totals.candidates} tint="cyan" />
                  <FunnelStage icon={PhoneCall} label="Called" value={data.totals.calls} previous={data.totals.shortlisted} tint="violet" />
                  <FunnelStage icon={CheckCircle2} label="Completed" value={data.call_stats.completed} previous={data.totals.calls} tint="emerald" />
                  <FunnelStage icon={Heart} label="Interested" value={data.call_stats.interested} previous={data.call_stats.completed} tint="rose" />
                </CardContent>
              </Card>

              <NeedsAttention
                overview={data}
                hunarConfigured={config.data?.hunar.configured ?? null}
              />
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <Card className="workspace-card">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <span className="flex size-7 items-center justify-center rounded-lg bg-teal-50 text-primary"><Briefcase className="size-3.5" /></span>
                    Recent jobs
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {data.recent_jobs.length ? (
                    <ul className="divide-y">
                      {data.recent_jobs.map((job) => (
                        <li key={job.id}>
                          <Link
                            href={`/jobs/${job.id}`}
                            className="hover:bg-secondary/50 -mx-2 flex items-center justify-between gap-3 rounded-md px-2 py-2.5 transition-colors"
                          >
                            <div className="min-w-0">
                              <div className="truncate text-sm font-medium">{job.title}</div>
                              <div className="text-muted-foreground truncate text-xs">
                                {job.company || "Company not provided"} · {formatRelative(job.created_at)}
                              </div>
                            </div>
                            <ArrowRight className="text-muted-foreground size-4 shrink-0" />
                          </Link>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <EmptyState
                      icon={Briefcase}
                      title="No jobs yet"
                      description="Paste a job description to parse it into search criteria and a screening script."
                      action={
                        <Button asChild size="sm">
                          <Link href="/jobs/new">Add a job description</Link>
                        </Button>
                      }
                    />
                  )}
                </CardContent>
              </Card>

              <Card className="workspace-card">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <span className="flex size-7 items-center justify-center rounded-lg bg-teal-50 text-teal-700"><PhoneCall className="size-3.5" /></span>
                    Recent campaigns
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {data.recent_campaigns.length ? (
                    <ul className="divide-y">
                      {data.recent_campaigns.map((campaign) => (
                        <li key={campaign.id}>
                          <Link
                            href={`/campaigns/${campaign.id}`}
                            className="hover:bg-secondary/50 -mx-2 flex items-center justify-between gap-3 rounded-md px-2 py-2.5 transition-colors"
                          >
                            <div className="min-w-0">
                              <div className="truncate text-sm font-medium">
                                {campaign.name}
                              </div>
                              <div className="text-muted-foreground truncate text-xs">
                                {campaign.stats.completed}/{campaign.stats.total} calls done
                                · {formatRelative(campaign.created_at)}
                              </div>
                            </div>
                            <ArrowRight className="text-muted-foreground size-4 shrink-0" />
                          </Link>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <EmptyState
                      icon={Users}
                      title="No campaigns yet"
                      description="Shortlist candidates on a job, then launch a voice screening campaign."
                    />
                  )}
                </CardContent>
              </Card>
            </div>
          </>
        ) : null}
      </div>
    </>
  );
}

function FunnelStage({
  icon: Icon,
  label,
  value,
  previous,
  tint,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number;
  previous: number | null;
  tint: "blue" | "cyan" | "violet" | "emerald" | "rose";
}) {
  const palette = {
    blue: "bg-teal-100 text-teal-700 dark:bg-teal-950 dark:text-teal-300",
    cyan: "bg-cyan-100 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-300",
    violet: "bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300",
    emerald: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
    rose: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
  };
  const conversion = previous === null ? null : previous ? Math.round((value / previous) * 100) : 0;
  return (
    <div className="rounded-xl border border-border/70 bg-background/80 p-3 sm:p-3.5">
      <div className="flex items-center justify-between gap-2">
        <span className={`flex size-8 items-center justify-center rounded-lg ${palette[tint]}`}><Icon className="size-4" /></span>
        <span className="text-muted-foreground text-[11px] tabular-nums">
          {conversion === null ? "Starting pool" : `${conversion}% conversion`}
        </span>
      </div>
      <div className="mt-3 text-2xl font-semibold tracking-tight tabular-nums">{value.toLocaleString()}</div>
      <div className="text-muted-foreground mt-0.5 text-xs font-medium">{label}</div>
      {conversion !== null ? <Progress value={Math.min(conversion, 100)} className="mt-3 h-1" /> : <div className="mt-3 h-1 rounded-full bg-teal-200 dark:bg-teal-900" />}
    </div>
  );
}

function NeedsAttention({
  overview,
  hunarConfigured,
}: {
  overview: DashboardOverview;
  hunarConfigured: boolean | null;
}) {
  const items: Array<{ title: string; detail: string; href: string; tone?: "warning" | "info" }> = [];
  if (hunarConfigured === false) {
    items.push({ title: "Voice screening isn't connected", detail: "Add a Hunar API key before placing calls.", href: "/settings", tone: "warning" });
  }
  if (overview.totals.candidates && !overview.totals.shortlisted) {
    items.push({ title: "Shortlist candidates", detail: `${overview.totals.candidates} profiles are waiting for review.`, href: "/jobs" });
  }
  if (overview.call_stats.failed) {
    const failedCampaign = overview.recent_campaigns.find((campaign) => campaign.stats.failed);
    items.push({ title: `${overview.call_stats.failed} failed calls`, detail: "Review the call details and retry if appropriate.", href: failedCampaign ? `/campaigns/${failedCampaign.id}` : "/campaigns", tone: "warning" });
  }
  if (overview.call_stats.do_not_contact) {
    items.push({ title: "Contact requests need review", detail: `${overview.call_stats.do_not_contact} candidate(s) asked not to be contacted.`, href: "/campaigns", tone: "warning" });
  }

  return (
    <Card className="workspace-card h-full">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <div className="eyebrow text-muted-foreground">Operations</div>
          <CardTitle className="mt-1 text-lg">Needs attention</CardTitle>
        </div>
        <Badge variant={items.length ? "destructive" : "secondary"}>{items.length || "All clear"}</Badge>
      </CardHeader>
      <CardContent>
        {items.length ? (
          <ul className="divide-y">
            {items.slice(0, 4).map((item) => (
              <li key={item.title}>
                <Link href={item.href} className="group flex items-start gap-3 py-3">
                  <span className={`mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg ${item.tone === "warning" ? "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300" : "bg-teal-100 text-teal-700 dark:bg-teal-950 dark:text-teal-300"}`}>
                    {item.tone === "warning" ? <AlertTriangle className="size-3.5" /> : <ArrowUpRight className="size-3.5" />}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium group-hover:text-primary">{item.title}</span>
                    <span className="text-muted-foreground mt-0.5 block text-xs leading-5">{item.detail}</span>
                  </span>
                  <ArrowRight className="text-muted-foreground mt-1 size-3.5 shrink-0 opacity-0 transition group-hover:translate-x-0.5 group-hover:opacity-100" />
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <div className="flex min-h-36 flex-col items-center justify-center text-center">
            <span className="flex size-10 items-center justify-center rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"><CheckCircle2 className="size-5" /></span>
            <div className="mt-3 text-sm font-medium">Everything looks good</div>
            <p className="text-muted-foreground mt-1 max-w-56 text-xs">No failed calls or follow-ups need your attention.</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DemoJourney() {
  const steps = [
    { icon: Briefcase, title: "Use a sample job", detail: "Open a ready-made backend role and analyse it.", active: true },
    { icon: Database, title: "Source candidates", detail: "Pull deterministic synthetic records from the mock provider." },
    { icon: Waves, title: "Launch a dry run", detail: "Select candidates and test the voice-screening flow safely." },
  ];

  return (
    <section className="relative overflow-hidden rounded-2xl border border-primary/15 bg-[linear-gradient(120deg,oklch(0.24_0.055_190),oklch(0.34_0.08_178)_55%,oklch(0.38_0.09_155))] p-6 text-white shadow-xl shadow-teal-950/10 sm:p-8">
      <div className="absolute -top-20 right-4 size-64 rounded-full bg-cyan-300/10 blur-3xl" />
      <div className="relative grid gap-8 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:items-end">
        <div>
          <div className="mb-3 inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/10 px-2.5 py-1 text-[11px] font-semibold tracking-wide text-cyan-100 uppercase">
            <Play className="size-3 fill-current" /> Guided demo
          </div>
          <h2 className="max-w-md text-2xl font-semibold tracking-tight sm:text-3xl">See the complete HireFlow workflow in a few minutes.</h2>
          <p className="mt-3 max-w-lg text-sm leading-6 text-teal-100">Explore the product with a sample role and fictional synthetic candidates. No personal data is used, and dry run keeps the voice campaign safe to test.</p>
          <Button asChild className="mt-5 bg-cyan-300 text-slate-950 hover:bg-cyan-200">
            <Link href="/jobs/new">Start demo <ArrowRight className="size-4" /></Link>
          </Button>
        </div>
        <ol className="grid gap-3 sm:grid-cols-3">
          {steps.map(({ icon: Icon, title, detail, active }, index) => (
            <li key={title} className="rounded-xl border border-white/10 bg-slate-950/15 p-4 backdrop-blur-sm">
              <div className="mb-5 flex items-center justify-between">
                <span className="flex size-8 items-center justify-center rounded-lg bg-white/10 text-cyan-200"><Icon className="size-4" /></span>
                {active ? <span className="flex size-5 items-center justify-center rounded-full bg-cyan-300 text-slate-900"><Check className="size-3" /></span> : <span className="text-xs font-semibold text-teal-200">0{index + 1}</span>}
              </div>
              <div className="text-sm font-semibold">{title}</div>
              <p className="mt-1.5 text-xs leading-5 text-teal-100/80">{detail}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
