"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  AudioLines,
  Briefcase,
  LayoutDashboard,
  PhoneCall,
  Settings2,
  Sparkles,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { getConfig } from "@/lib/api";
import type { AppConfig } from "@/lib/types";
import { Badge } from "@/components/ui/badge";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard, exact: true },
  { href: "/jobs", label: "Jobs", icon: Briefcase },
  { href: "/campaigns", label: "Campaigns", icon: PhoneCall },
  { href: "/settings", label: "Settings", icon: Settings2 },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    getConfig()
      .then(setConfig)
      .catch(() => setOffline(true));
  }, []);

  return (
    <div className="flex min-h-screen bg-background">
      <aside className="hidden w-64 shrink-0 flex-col bg-sidebar text-sidebar-foreground md:flex">
        <div className="flex h-[76px] items-center gap-3 border-b border-sidebar-border px-5">
          <div className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-300 to-teal-400 text-slate-900 shadow-lg shadow-cyan-950/20">
            <AudioLines className="size-5" aria-hidden />
          </div>
          <div>
            <div className="text-[15px] font-semibold tracking-tight">HireFlow AI</div>
            <div className="text-[10px] font-medium tracking-[0.12em] text-cyan-200/70 uppercase">Talent operations</div>
          </div>
        </div>

        <nav className="flex-1 space-y-1 p-3 pt-5">
          <p className="px-3 pb-2 text-[10px] font-semibold tracking-[0.14em] text-slate-400 uppercase">Workspace</p>
          {NAV.map(({ href, label, icon: Icon, exact }) => {
            const active = exact ? pathname === href : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm transition-colors",
                  active
                    ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium shadow-sm"
                    : "text-slate-300 hover:bg-white/8 hover:text-white",
                )}
              >
                <Icon className="size-4" aria-hidden />
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="mx-3 mb-3 rounded-xl border border-white/10 bg-white/5 p-3 text-xs">
          <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold tracking-[0.12em] text-cyan-100/75 uppercase">
            <Sparkles className="size-3" /> System status
          </div>
          <div className="space-y-2">
            <StatusLine
              label="Voice AI"
              ok={config?.hunar.configured}
              offline={offline}
              detail={config?.hunar.configured ? "Hunar connected" : "No API key"}
            />
            <StatusLine
              label="Sourcing"
              ok={Boolean(config)}
              offline={offline}
              detail={
                config?.providers.find((p) => p.active)?.label ?? config?.people_provider
              }
              tone={config?.people_provider === "mock" ? "warning" : "ok"}
            />
            <StatusLine
              label="Callbacks"
              ok={config?.webhooks.available}
              offline={offline}
              detail={config?.webhooks.available ? "Webhooks live" : "Polling"}
              tone={config?.webhooks.available ? "ok" : "warning"}
            />
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <MobileNav pathname={pathname} />
        {config?.demo_call_redirect.enabled ? (
          <div className="border-b border-amber-200 bg-amber-50 px-6 py-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
            <strong className="font-medium">Demo redirect active.</strong> Every call is
            placed to {config.demo_call_redirect.number}, not to the sourced candidate.
          </div>
        ) : null}
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}

function StatusLine({
  label,
  ok,
  detail,
  offline,
  tone = "ok",
}: {
  label: string;
  ok: boolean | undefined;
  detail?: string | null;
  offline: boolean;
  tone?: "ok" | "warning";
}) {
  const state = offline ? "down" : ok === undefined ? "loading" : ok ? tone : "warning";
  const dot = {
    loading: "bg-muted-foreground/40",
    ok: "bg-emerald-500",
    warning: "bg-amber-500",
    down: "bg-red-500",
  }[state];

  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-slate-400">{label}</span>
      <span className="flex items-center gap-1.5 truncate">
        <span className={cn("size-1.5 shrink-0 rounded-full", dot)} aria-hidden />
        <span className="truncate" title={detail ?? undefined}>
          {offline ? "API offline" : (detail ?? "…")}
        </span>
      </span>
    </div>
  );
}

function MobileNav({ pathname }: { pathname: string }) {
  return (
    <div className="flex h-14 items-center gap-1 overflow-x-auto border-b bg-sidebar px-3 md:hidden">
      <AudioLines className="mr-1 size-4 shrink-0 text-cyan-300" aria-hidden />
      {NAV.map(({ href, label, exact }) => {
        const active = exact ? pathname === href : pathname.startsWith(href);
        return (
          <Link key={href} href={href}>
            <Badge
              variant={active ? "default" : "secondary"}
              className={cn("whitespace-nowrap", !active && "border-white/10 bg-white/10 text-slate-200")}
            >
              {label}
            </Badge>
          </Link>
        );
      })}
    </div>
  );
}
