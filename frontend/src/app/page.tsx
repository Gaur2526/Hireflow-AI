"use client";

import Link from "next/link";
import {
  ArrowRight,
  Briefcase,
  Check,
  Database,
  PhoneCall,
  Play,
  Plus,
  Users,
  Waves,
} from "lucide-react";

import { getOverview } from "@/lib/api";
import { formatDuration, formatRelative } from "@/lib/format";
import { useAsync } from "@/hooks/use-async";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  EmptyState,
  ErrorNote,
  PageHeader,
  SkeletonRows,
  StatCard,
} from "@/components/primitives";

export default function DashboardPage() {
  const { data, error, loading } = useAsync(getOverview);

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

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <StatCard label="Jobs" value={data.totals.jobs} />
              <StatCard
                label="Sourced"
                value={data.totals.candidates}
                hint={`${data.totals.shortlisted} shortlisted`}
              />
              <StatCard label="Campaigns" value={data.totals.campaigns} />
              <StatCard
                label="Calls placed"
                value={data.totals.calls}
                hint={`${data.call_stats.completed} completed`}
              />
              <StatCard
                label="Interested"
                value={data.call_stats.interested}
                tone={data.call_stats.interested ? "positive" : undefined}
                hint={
                  data.call_stats.avg_duration_seconds
                    ? `avg ${formatDuration(data.call_stats.avg_duration_seconds)} on call`
                    : undefined
                }
              />
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <Card className="workspace-card">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <span className="flex size-7 items-center justify-center rounded-lg bg-blue-50 text-primary"><Briefcase className="size-3.5" /></span>
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
                                {job.company ?? "—"} · {formatRelative(job.created_at)}
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

function DemoJourney() {
  const steps = [
    { icon: Briefcase, title: "Use a sample job", detail: "Open a ready-made backend role and analyse it.", active: true },
    { icon: Database, title: "Source candidates", detail: "Pull deterministic synthetic records from the mock provider." },
    { icon: Waves, title: "Launch a dry run", detail: "Select candidates and test the voice-screening flow safely." },
  ];

  return (
    <section className="relative overflow-hidden rounded-2xl border border-primary/15 bg-[linear-gradient(120deg,oklch(0.25_0.07_258),oklch(0.36_0.11_254)_55%,oklch(0.37_0.09_218))] p-6 text-white shadow-xl shadow-blue-950/10 sm:p-8">
      <div className="absolute -top-20 right-4 size-64 rounded-full bg-cyan-300/10 blur-3xl" />
      <div className="relative grid gap-8 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:items-end">
        <div>
          <div className="mb-3 inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/10 px-2.5 py-1 text-[11px] font-semibold tracking-wide text-cyan-100 uppercase">
            <Play className="size-3 fill-current" /> Guided demo
          </div>
          <h2 className="max-w-md text-2xl font-semibold tracking-tight sm:text-3xl">See the complete HireFlow workflow in a few minutes.</h2>
          <p className="mt-3 max-w-lg text-sm leading-6 text-blue-100">Explore the product with a sample role and fictional synthetic candidates. No personal data is used, and dry run keeps the voice campaign safe to test.</p>
          <Button asChild className="mt-5 bg-cyan-300 text-slate-950 hover:bg-cyan-200">
            <Link href="/jobs/new">Start demo <ArrowRight className="size-4" /></Link>
          </Button>
        </div>
        <ol className="grid gap-3 sm:grid-cols-3">
          {steps.map(({ icon: Icon, title, detail, active }, index) => (
            <li key={title} className="rounded-xl border border-white/10 bg-slate-950/15 p-4 backdrop-blur-sm">
              <div className="mb-5 flex items-center justify-between">
                <span className="flex size-8 items-center justify-center rounded-lg bg-white/10 text-cyan-200"><Icon className="size-4" /></span>
                {active ? <span className="flex size-5 items-center justify-center rounded-full bg-cyan-300 text-slate-900"><Check className="size-3" /></span> : <span className="text-xs font-semibold text-blue-200">0{index + 1}</span>}
              </div>
              <div className="text-sm font-semibold">{title}</div>
              <p className="mt-1.5 text-xs leading-5 text-blue-100/80">{detail}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
