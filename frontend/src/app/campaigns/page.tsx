"use client";

import Link from "next/link";
import { PhoneCall } from "lucide-react";

import { listCampaigns } from "@/lib/api";
import { formatRelative } from "@/lib/format";
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
                  <TableHead>Job</TableHead>
                  <TableHead className="w-48">Progress</TableHead>
                  <TableHead className="text-right">Interested</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
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
                          className="hover:underline"
                        >
                          {campaign.name}
                        </Link>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        <Link href={`/jobs/${campaign.job_id}`} className="hover:underline">
                          {campaign.job_title || "—"}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Progress value={pct} className="h-1.5" />
                          <span className="text-muted-foreground w-14 shrink-0 text-right text-xs tabular-nums">
                            {done}/{campaign.stats.total}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {campaign.stats.interested}
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary">{campaign.status}</Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-sm">
                        {formatRelative(campaign.created_at)}
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
