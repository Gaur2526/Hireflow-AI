"use client";

import Link from "next/link";
import { Briefcase, Plus, Sparkles } from "lucide-react";

import { listJobs } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { useAsync } from "@/hooks/use-async";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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

export default function JobsPage() {
  const { data, error, loading } = useAsync(listJobs);

  return (
    <>
      <PageHeader
        title="Jobs"
        description="Each job holds the parsed search criteria and the screening script its voice agent will follow."
        actions={
          <Button asChild>
            <Link href="/jobs/new">
              <Plus className="size-4" /> New job
            </Link>
          </Button>
        }
      />

      <div className="space-y-4 p-6">
        {error ? <ErrorNote message={error} /> : null}
        {loading && !data ? <SkeletonRows /> : null}

        {data && data.length === 0 ? (
          <EmptyState
            icon={Briefcase}
            title="No jobs yet"
            description="Paste a job description and it becomes search criteria plus a voice screening script."
            action={
              <Button asChild>
                <Link href="/jobs/new">Add a job description</Link>
              </Button>
            }
          />
        ) : null}

        {data && data.length > 0 ? (
          <div className="rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Role</TableHead>
                  <TableHead>Company</TableHead>
                  <TableHead className="text-right">Sourced</TableHead>
                  <TableHead className="text-right">Shortlisted</TableHead>
                  <TableHead className="text-right">Calls</TableHead>
                  <TableHead>Parsed by</TableHead>
                  <TableHead>Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((job) => (
                  <TableRow key={job.id}>
                    <TableCell className="font-medium">
                      <Link href={`/jobs/${job.id}`} className="hover:underline">
                        {job.title}
                      </Link>
                      {job.location ? (
                        <div className="text-muted-foreground text-xs">{job.location}</div>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {job.company ?? "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {job.candidate_count}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {job.shortlisted_count}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {job.call_count}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="gap-1 font-normal">
                        {job.parsed_by === "llm" ? (
                          <>
                            <Sparkles className="size-3" /> Claude
                          </>
                        ) : (
                          "Rules"
                        )}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {formatRelative(job.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : null}
      </div>
    </>
  );
}
