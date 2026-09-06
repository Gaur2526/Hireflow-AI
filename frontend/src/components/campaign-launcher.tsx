"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Loader2, PhoneOutgoing } from "lucide-react";
import { toast } from "sonner";

import { launchCampaign } from "@/lib/api";
import type { AppConfig, CallDefaults, Job } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ErrorNote } from "@/components/primitives";

const DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];
// Hunar rejects anything outside this set.
const RETRY_INTERVALS = [0, 3, 6, 9, 12, 24];

export function CampaignLauncher({
  job,
  config,
  selectedIds,
}: {
  job: Job;
  config: AppConfig | null;
  selectedIds: string[];
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(`HireFlow AI — ${job.title}`.slice(0, 64));
  // getConfig() resolves independently of the job, so `config` is usually still
  // null on first render. Fall through to it until the operator picks something,
  // rather than freezing the deployment's defaults out of a useState initialiser.
  const [personaChoice, setPersonaChoice] = useState<string | null>(null);
  const persona = personaChoice ?? config?.defaults.voice_persona ?? "NEHA";
  const [personaName, setPersonaName] = useState("Asha");
  const [languageChoice, setLanguageChoice] = useState<string | null>(null);
  const language = languageChoice ?? config?.defaults.language ?? "ENGLISH";
  const [dryRun, setDryRun] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [timezoneChoice, setTimezoneChoice] = useState<string | null>(null);
  const timezone = timezoneChoice ?? config?.defaults.timezone ?? "Asia/Kolkata";

  const [defaults, setDefaults] = useState<Omit<CallDefaults, "timezone">>({
    max_retry_count: 1,
    retry_interval_hours: 6,
    allowed_days: ["MON", "TUE", "WED", "THU", "FRI"],
    earliest_call_time: "10:00",
    last_call_time: "19:00",
  });

  function toggleDay(day: string) {
    setDefaults((prev) => ({
      ...prev,
      allowed_days: prev.allowed_days.includes(day)
        ? prev.allowed_days.filter((d) => d !== day)
        : [...prev.allowed_days, day],
    }));
  }

  async function launch() {
    setBusy(true);
    setError(null);
    try {
      const response = await launchCampaign(job.id, {
        name,
        candidate_ids: selectedIds,
        dry_run: dryRun,
        agent_config: {
          language,
          voice_persona: persona,
          persona_name: personaName || null,
        },
        call_defaults: { ...defaults, timezone },
      });

      if (response.dispatched) {
        toast.success(`${response.dispatched} call${response.dispatched === 1 ? "" : "s"} placed`, {
          description: "Answers will appear as each call finishes.",
        });
      } else {
        toast.warning("Agent created, no calls placed", {
          description:
            response.skipped[0]?.reason ?? response.warnings[0] ?? "Nothing was dialable.",
        });
      }
      setOpen(false);
      router.push(`/campaigns/${response.campaign.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  const hunarReady = config?.hunar.configured ?? false;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button disabled={!selectedIds.length}>
          <PhoneOutgoing className="size-4" />
          Screen {selectedIds.length || ""} by voice
        </Button>
      </DialogTrigger>

      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Launch voice screening</DialogTitle>
          <DialogDescription>
            Creates a Hunar agent from this job&apos;s screening script, then calls the{" "}
            {selectedIds.length} selected candidate
            {selectedIds.length === 1 ? "" : "s"}.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="campaign-name">Campaign name</Label>
            <Input
              id="campaign-name"
              value={name}
              maxLength={64}
              onChange={(event) => setName(event.target.value)}
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="voice">Voice</Label>
              <Select value={persona} onValueChange={setPersonaChoice}>
                <SelectTrigger id="voice">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(config?.voice_options.personas ?? ["NEHA"]).map((option) => (
                    <SelectItem key={option} value={option}>
                      {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="language">Language</Label>
              <Select value={language} onValueChange={setLanguageChoice}>
                <SelectTrigger id="language">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(config?.voice_options.languages ?? ["ENGLISH"]).map((option) => (
                    <SelectItem key={option} value={option}>
                      {option.charAt(0) + option.slice(1).toLowerCase()}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="persona-name">Introduces self as</Label>
              <Input
                id="persona-name"
                value={personaName}
                onChange={(event) => setPersonaName(event.target.value)}
                placeholder="Asha"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>Calling days</Label>
            <div className="flex flex-wrap gap-1">
              {DAYS.map((day) => {
                const on = defaults.allowed_days.includes(day);
                return (
                  <Button
                    key={day}
                    type="button"
                    size="sm"
                    variant={on ? "default" : "outline"}
                    className="h-7 px-2.5 text-xs"
                    onClick={() => toggleDay(day)}
                  >
                    {day}
                  </Button>
                );
              })}
            </div>
            {defaults.allowed_days.length < 3 ? (
              <p className="text-xs text-amber-600">Hunar requires at least three days.</p>
            ) : null}
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="from-time">Call from</Label>
              <Input
                id="from-time"
                type="time"
                value={defaults.earliest_call_time}
                onChange={(event) =>
                  setDefaults((prev) => ({ ...prev, earliest_call_time: event.target.value }))
                }
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="to-time">until</Label>
              <Input
                id="to-time"
                type="time"
                value={defaults.last_call_time}
                onChange={(event) =>
                  setDefaults((prev) => ({ ...prev, last_call_time: event.target.value }))
                }
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="timezone">Timezone</Label>
              <Select value={timezone} onValueChange={setTimezoneChoice}>
                <SelectTrigger id="timezone">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(config?.voice_options.timezones ?? ["Asia/Kolkata"]).map((zone) => (
                    <SelectItem key={zone} value={zone}>
                      {zone}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="retries">Retries if not connected</Label>
              <Input
                id="retries"
                type="number"
                min={0}
                max={10}
                value={defaults.max_retry_count}
                onChange={(event) =>
                  setDefaults((prev) => ({
                    ...prev,
                    max_retry_count: Number(event.target.value),
                  }))
                }
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="retry-interval">Hours between retries</Label>
              <Select
                value={String(defaults.retry_interval_hours)}
                onValueChange={(value) =>
                  setDefaults((prev) => ({
                    ...prev,
                    retry_interval_hours: Number(value),
                  }))
                }
              >
                <SelectTrigger id="retry-interval">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {RETRY_INTERVALS.map((hours) => (
                    <SelectItem key={hours} value={String(hours)}>
                      {hours}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <label className="flex items-start gap-3 rounded-xl border border-cyan-200 bg-cyan-50/70 p-3 text-sm">
            <Checkbox
              checked={dryRun}
              onCheckedChange={(value) => setDryRun(Boolean(value))}
              className="mt-0.5"
            />
            <span className="text-cyan-950">
              <span className="font-medium">Dry run <span className="ml-1 rounded-full bg-cyan-200 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-cyan-900 uppercase">Recommended for demo</span></span>
              <span className="mt-1 block text-xs text-cyan-800">
                Create the Hunar agent and queue calls without dialing anyone.
              </span>
            </span>
          </label>

          {!hunarReady ? (
            <ErrorNote message="HUNAR_API_KEY is not configured on the backend, so no call can be placed." />
          ) : null}
          {config?.demo_call_redirect.enabled ? (
            <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
              Demo redirect is on — every call goes to {config.demo_call_redirect.number}.
            </p>
          ) : null}
          {error ? <ErrorNote message={error} /> : null}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            onClick={launch}
            disabled={busy || !hunarReady || defaults.allowed_days.length < 3}
          >
            {busy ? <Loader2 className="size-4 animate-spin" /> : null}
            {dryRun ? "Create agent" : `Call ${selectedIds.length}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
