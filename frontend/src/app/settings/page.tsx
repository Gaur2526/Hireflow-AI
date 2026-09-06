"use client";

import { AlertTriangle, CheckCircle2, ExternalLink, XCircle } from "lucide-react";

import { getConfig, listWebhookEvents, pingHunar } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { useAsync } from "@/hooks/use-async";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import {
  EmptyState,
  ErrorNote,
  PageHeader,
  SkeletonRows,
} from "@/components/primitives";

export default function SettingsPage() {
  const config = useAsync(getConfig);
  const ping = useAsync(pingHunar);
  const events = useAsync(() => listWebhookEvents(15));

  return (
    <>
      <PageHeader
        title="Settings"
        description="What this deployment is wired up to. Credentials live in the backend environment — this page only reports whether they are present."
      />

      <div className="grid gap-4 p-6 lg:grid-cols-2">
        {config.error ? <ErrorNote message={config.error} /> : null}
        {config.loading && !config.data ? <SkeletonRows rows={4} /> : null}

        {config.data ? (
          <>
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Voice AI — Hunar</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <Row
                  label="API key"
                  ok={config.data.hunar.configured}
                  value={
                    config.data.hunar.configured
                      ? config.data.hunar.key_fingerprint
                      : "not set"
                  }
                />
                <Row label="Base URL" ok value={config.data.hunar.base_url} />
                <Row
                  label="Live check"
                  ok={ping.data?.ok}
                  value={
                    ping.loading
                      ? "checking…"
                      : ping.data?.ok
                        ? `reachable · ${ping.data.agents_visible} agents visible`
                        : (ping.data?.reason ?? "unreachable")
                  }
                />
                <Row
                  label="Webhook signing"
                  ok
                  value={
                    config.data.hunar.webhook_secret_set
                      ? "dedicated secret"
                      : "API key (Hunar default)"
                  }
                />
                <Separator />
                <Row
                  label="Callbacks"
                  ok={config.data.webhooks.available}
                  warn={!config.data.webhooks.available}
                  value={
                    config.data.webhooks.available
                      ? (config.data.webhooks.public_base_url ?? "configured")
                      : `polling every ${config.data.webhooks.poll_interval_seconds}s — set PUBLIC_BASE_URL to an https URL for webhooks`
                  }
                />
                {config.data.demo_call_redirect.enabled ? (
                  <Row
                    label="Demo redirect"
                    warn
                    value={`all calls go to ${config.data.demo_call_redirect.number}`}
                  />
                ) : null}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">People search</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {config.data.providers.map((provider) => (
                  <div
                    key={provider.name}
                    className="flex items-start justify-between gap-3 text-sm"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{provider.label}</span>
                        {provider.active ? <Badge className="h-5">active</Badge> : null}
                        {provider.retired ? (
                          <Badge variant="outline" className="h-5">
                            retired
                          </Badge>
                        ) : null}
                        {provider.docs_url ? (
                          <a
                            href={provider.docs_url}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="text-muted-foreground hover:text-foreground"
                            aria-label={`${provider.label} docs`}
                          >
                            <ExternalLink className="size-3" />
                          </a>
                        ) : null}
                      </div>
                      {provider.note ? (
                        <p className="text-muted-foreground mt-0.5 text-xs">
                          {provider.note}
                        </p>
                      ) : null}
                    </div>
                    <StatusIcon
                      ok={provider.configured}
                      warn={provider.retired || (!provider.configured && !provider.retired)}
                    />
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Job-description parsing</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <Row
                  label="LLM"
                  ok={config.data.llm.configured}
                  warn={!config.data.llm.configured}
                  value={
                    config.data.llm.configured
                      ? (config.data.llm.model ?? "configured")
                      : "no ANTHROPIC_API_KEY — using the built-in deterministic parser"
                  }
                />
                <p className="text-muted-foreground text-xs">
                  Everything works without a key. With one, criteria extraction and
                  screening-question design are done by Claude instead of rules.
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Recent webhook callbacks</CardTitle>
              </CardHeader>
              <CardContent>
                {events.data?.length ? (
                  <ul className="divide-y text-sm">
                    {events.data.map((event) => (
                      <li key={event.id} className="flex items-start gap-2 py-2">
                        <StatusIcon
                          ok={event.signature_valid === true && event.handled}
                          warn={event.signature_valid !== true}
                        />
                        <div className="min-w-0 flex-1">
                          <div className="font-mono text-xs">{event.event_type}</div>
                          <div className="text-muted-foreground text-xs">
                            {event.note ?? "—"} · {formatRelative(event.received_at)}
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <EmptyState
                    title="No callbacks received"
                    description="Hunar posts here when a call changes status, finishes recording, or produces results. Without a public HTTPS URL the app polls instead."
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

function Row({
  label,
  value,
  ok,
  warn,
}: {
  label: string;
  value: string;
  ok?: boolean;
  warn?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-muted-foreground shrink-0">{label}</span>
      <span className="flex min-w-0 items-start gap-1.5 text-right">
        <span className="min-w-0 break-words">{value}</span>
        <StatusIcon ok={ok} warn={warn} />
      </span>
    </div>
  );
}

function StatusIcon({ ok, warn }: { ok?: boolean; warn?: boolean }) {
  if (ok && !warn) {
    return <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-500" aria-label="ok" />;
  }
  if (warn) {
    return (
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-500" aria-label="warning" />
    );
  }
  return <XCircle className="text-muted-foreground/50 mt-0.5 size-4 shrink-0" aria-label="not set" />;
}
