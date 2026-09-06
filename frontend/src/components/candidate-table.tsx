"use client";

import { useState } from "react";
import { ExternalLink, Phone, PhoneOff } from "lucide-react";
import { toast } from "sonner";

import { setCandidatePhone } from "@/lib/api";
import { formatPhone } from "@/lib/format";
import type { Candidate } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { CandidateStatusBadge, Chips, FitScore } from "@/components/primitives";

export function CandidateTable({
  candidates,
  selected,
  onToggle,
  onToggleAll,
  onCandidateUpdated,
}: {
  candidates: Candidate[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: (ids: string[], value: boolean) => void;
  onCandidateUpdated: (candidate: Candidate) => void;
}) {
  const callable = candidates.filter((c) => c.phone);
  const allSelected =
    callable.length > 0 && callable.every((c) => selected.has(c.id));

  return (
    <div className="rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-10">
              <Checkbox
                checked={allSelected}
                onCheckedChange={(value) =>
                  onToggleAll(
                    callable.map((c) => c.id),
                    Boolean(value),
                  )
                }
                aria-label="Select all callable candidates"
              />
            </TableHead>
            <TableHead>Candidate</TableHead>
            <TableHead className="w-16 text-right">Fit</TableHead>
            <TableHead>Why</TableHead>
            <TableHead>Skills</TableHead>
            <TableHead className="w-40">Phone</TableHead>
            <TableHead className="w-32">Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {candidates.map((candidate) => (
            <TableRow key={candidate.id} data-state={selected.has(candidate.id) ? "selected" : undefined}>
              <TableCell>
                <Checkbox
                  checked={selected.has(candidate.id)}
                  disabled={!candidate.phone}
                  onCheckedChange={() => onToggle(candidate.id)}
                  aria-label={`Select ${candidate.full_name}`}
                />
              </TableCell>

              <TableCell>
                <div className="flex items-center gap-1.5 font-medium">
                  {candidate.full_name}
                  {candidate.linkedin_url ? (
                    <a
                      href={candidate.linkedin_url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="text-muted-foreground hover:text-foreground"
                      aria-label={`${candidate.full_name} on LinkedIn`}
                    >
                      <ExternalLink className="size-3" />
                    </a>
                  ) : null}
                </div>
                <div className="text-muted-foreground text-xs">
                  {candidate.title ?? "—"}
                  {candidate.company ? ` · ${candidate.company}` : ""}
                </div>
                <div className="text-muted-foreground text-xs">
                  {candidate.location ?? "—"}
                  {candidate.years_experience
                    ? ` · ${candidate.years_experience} yrs`
                    : ""}
                </div>
              </TableCell>

              <TableCell className="text-right">
                <FitScore score={candidate.fit_score} />
              </TableCell>

              <TableCell className="max-w-[260px]">
                <ul className="text-muted-foreground space-y-0.5 text-xs">
                  {candidate.fit_reasons.slice(0, 3).map((reason, index) => (
                    <li key={index} className="truncate" title={reason}>
                      {reason}
                    </li>
                  ))}
                </ul>
              </TableCell>

              <TableCell className="max-w-[220px]">
                <Chips items={candidate.skills} max={4} />
              </TableCell>

              <TableCell>
                <PhoneCell candidate={candidate} onUpdated={onCandidateUpdated} />
              </TableCell>

              <TableCell>
                <CandidateStatusBadge status={candidate.status} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function PhoneCell({
  candidate,
  onUpdated,
}: {
  candidate: Candidate;
  onUpdated: (candidate: Candidate) => void;
}) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(candidate.phone ?? "");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      const updated = await setCandidatePhone(candidate.id, value);
      onUpdated(updated);
      toast.success(`Number saved for ${candidate.full_name}`);
      setOpen(false);
    } catch (cause) {
      toast.error("Could not save that number", {
        description: cause instanceof Error ? cause.message : String(cause),
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-auto justify-start px-2 py-1 font-normal">
          {candidate.phone ? (
            <span className="flex items-center gap-1.5">
              <Phone className="size-3 shrink-0" />
              <span className="font-mono text-xs">{formatPhone(candidate.phone)}</span>
              {!candidate.phone_is_valid ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Badge variant="outline" className="px-1 text-[10px]">
                      ?
                    </Badge>
                  </TooltipTrigger>
                  <TooltipContent>
                    This number parses but may not be dialable.
                  </TooltipContent>
                </Tooltip>
              ) : null}
            </span>
          ) : (
            <span className="text-muted-foreground flex items-center gap-1.5 text-xs">
              <PhoneOff className="size-3" /> Add number
            </span>
          )}
        </Button>
      </PopoverTrigger>

      <PopoverContent className="w-72 space-y-2" align="start">
        <p className="text-sm font-medium">Phone number</p>
        <p className="text-muted-foreground text-xs">
          Vendors rarely return a dialable mobile on free plans. Paste one in E.164 form
          (+91…) to make this candidate callable.
        </p>
        <Input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="+919876543210"
          onKeyDown={(event) => {
            if (event.key === "Enter") void save();
          }}
        />
        <Button size="sm" className="w-full" onClick={save} disabled={saving || !value.trim()}>
          Save
        </Button>
      </PopoverContent>
    </Popover>
  );
}
