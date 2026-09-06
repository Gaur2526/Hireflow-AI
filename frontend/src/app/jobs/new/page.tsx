"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Check, Loader2, Play, ScanSearch, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { createJob, parseJobDescription } from "@/lib/api";
import type { ParsePreview } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Chips, ErrorNote, PageHeader, WarningList } from "@/components/primitives";
import { ScreeningPlanCard } from "@/components/screening-plan-card";

const SAMPLE = `Senior Backend Engineer — Payments Platform

About the role
We process 4 million transactions a day and are hiring a Senior Backend Engineer for the Payments Platform team in Bengaluru, India. Hybrid, 3 days a week in office.

What you'll do
- Design and build low-latency payment APIs handling 10k TPS
- Own reliability, observability and on-call for core ledger services
- Mentor two mid-level engineers

Requirements
- 5-9 years of professional backend engineering experience
- Strong Python and Go, with deep PostgreSQL knowledge
- Production experience running Kubernetes, Docker and AWS
- Solid grasp of distributed systems and system design

Nice to have
- Kafka and event-driven architecture
- Exposure to gRPC and Terraform

Compensation: INR 45,00,000 - 65,00,000 per annum. Full-time.`;

export default function NewJobPage() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [company, setCompany] = useState("");
  const [location, setLocation] = useState("");
  const [description, setDescription] = useState("");
  const [preview, setPreview] = useState<ParsePreview | null>(null);
  const [parsing, setParsing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tooShort = description.trim().length < 40;

  async function analyse() {
    setParsing(true);
    setError(null);
    try {
      const result = await parseJobDescription({
        title: title || undefined,
        company: company || undefined,
        location: location || undefined,
        description,
      });
      setPreview(result);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setParsing(false);
    }
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const job = await createJob({
        title: title || undefined,
        company: company || undefined,
        location: location || undefined,
        description,
      });
      toast.success("Job saved", { description: "Now source candidates for it." });
      router.push(`/jobs/${job.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setSaving(false);
    }
  }

  return (
    <>
      <PageHeader
        title="New job"
        description="Paste the job description. It becomes the people-search query and the script the voice agent follows on every call."
        breadcrumb="Jobs / New"
      />

      <div className="grid gap-6 p-6 lg:grid-cols-2">
        <div className="space-y-4">
          <div className="flex items-center justify-between rounded-xl border border-cyan-200 bg-cyan-50/70 px-4 py-3 text-sm text-cyan-950">
            <div className="flex items-center gap-2"><span className="flex size-6 items-center justify-center rounded-full bg-cyan-600 text-white"><Play className="size-3 fill-current" /></span><span><strong>Demo step 1 of 3</strong> · Start with the sample role</span></div>
            {description ? <span className="hidden items-center gap-1 text-xs font-medium text-emerald-700 sm:flex"><Check className="size-3.5" /> Ready to analyse</span> : null}
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="title">Role title</Label>
              <Input
                id="title"
                placeholder="Auto-detected"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="company">Company</Label>
              <Input
                id="company"
                placeholder="Named on the call"
                value={company}
                onChange={(event) => setCompany(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="location">Location</Label>
              <Input
                id="location"
                placeholder="Auto-detected"
                value={location}
                onChange={(event) => setLocation(event.target.value)}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label htmlFor="jd">Job description</Label>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 rounded-md border border-cyan-200 bg-cyan-50 text-xs text-cyan-800 hover:bg-cyan-100"
                onClick={() => setDescription(SAMPLE)}
              >
                Use a sample
              </Button>
            </div>
            <Textarea
              id="jd"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Paste the full job description here…"
              className="min-h-[420px] font-mono text-xs leading-relaxed"
            />
            <p className="text-muted-foreground text-xs">
              {description.trim().length} characters
              {tooShort ? " — at least 40 needed" : ""}
            </p>
          </div>

          {error ? <ErrorNote message={error} /> : null}

          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={analyse} disabled={tooShort || parsing}>
              {parsing ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <ScanSearch className="size-4" />
              )}
              Analyse
            </Button>
            <Button onClick={save} disabled={tooShort || saving}>
              {saving ? <Loader2 className="size-4 animate-spin" /> : null}
              Save job
            </Button>
          </div>
        </div>

        <div className="space-y-4">
          {!preview ? (
            <Card className="border-dashed">
              <CardContent className="text-muted-foreground py-14 text-center text-sm">
                Hit <span className="text-foreground font-medium">Analyse</span> to see the
                search criteria and the screening questions this description produces —
                before you save anything.
              </CardContent>
            </Card>
          ) : null}

          {preview ? (
            <>
              <WarningList warnings={preview.warnings} />

              <Card>
                <CardHeader className="flex-row items-center justify-between gap-2 space-y-0">
                  <CardTitle className="text-base">Search criteria</CardTitle>
                  <Badge variant="secondary" className="gap-1 font-normal">
                    {preview.parsed_by === "llm" ? (
                      <>
                        <Sparkles className="size-3" /> Parsed by Claude
                      </>
                    ) : (
                      "Rule-based parser"
                    )}
                  </Badge>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <Field label="Titles to search">
                    <Chips items={preview.criteria.titles} />
                  </Field>
                  <Field label="Must have">
                    <Chips items={preview.criteria.must_have_skills} max={12} />
                  </Field>
                  <Field label="Nice to have">
                    <Chips items={preview.criteria.nice_to_have_skills} />
                  </Field>
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Experience">
                      <span>
                        {preview.criteria.min_years
                          ? `${preview.criteria.min_years}${
                              preview.criteria.max_years
                                ? `–${preview.criteria.max_years}`
                                : "+"
                            } years`
                          : "Not stated"}
                      </span>
                    </Field>
                    <Field label="Work mode">
                      <span className="capitalize">
                        {preview.criteria.work_mode ?? "Not stated"}
                      </span>
                    </Field>
                  </div>
                  <Field label="Locations">
                    <Chips items={preview.criteria.locations} />
                  </Field>
                  {preview.criteria.compensation ? (
                    <Field label="Compensation">
                      <span>{preview.criteria.compensation}</span>
                    </Field>
                  ) : null}
                </CardContent>
              </Card>

              <ScreeningPlanCard plan={preview.screening_plan} />
            </>
          ) : null}
        </div>
      </div>
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
        {label}
      </div>
      {children}
    </div>
  );
}
