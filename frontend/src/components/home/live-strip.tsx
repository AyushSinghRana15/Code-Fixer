"use client";

import Link from "next/link";
import { ArrowRightIcon } from "lucide-react";
import { CountUp } from "@/components/home/motion";
import { NAV_FORWARD } from "@/components/layout/transitions";
import { useAppState } from "@/hooks/use-app-state";

function Metric({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 px-5 py-4">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-2xl font-semibold tracking-tight">{children}</span>
    </div>
  );
}

/** A live peek at the agent, using the same store as the dashboard. */
export function LiveStrip() {
  const stats = useAppState((s) => s.stats);
  const providers = useAppState((s) => s.providers);
  const active = providers?.find((p) => p.id === stats?.activeProvider);
  const dash = <span className="text-muted-foreground/50">—</span>;

  return (
    <div className="overflow-hidden rounded-2xl border bg-card/60">
      <div className="flex items-center justify-between border-b px-5 py-2.5 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-2">
          <span className="size-1.5 animate-live rounded-full bg-brand" />
          Live from your agent
        </span>
        <Link
          href="/jobs"
          transitionTypes={NAV_FORWARD}
          className="group inline-flex items-center gap-1 hover:text-foreground"
        >
          Open dashboard
          <ArrowRightIcon className="size-3.5 transition-transform group-hover:translate-x-0.5" />
        </Link>
      </div>
      <div className="grid grid-cols-2 divide-border md:grid-cols-4 md:divide-x [&>*:nth-child(-n+2)]:border-b md:[&>*:nth-child(-n+2)]:border-b-0 [&>*:nth-child(odd)]:border-r md:[&>*:nth-child(odd)]:border-r-0">
        <Metric label="Jobs today">{stats ? <CountUp value={stats.jobsToday} /> : dash}</Metric>
        <Metric label="Success rate · 7 days">
          {stats?.successRate7d != null ? <CountUp value={stats.successRate7d * 100} format={(n) => `${Math.round(n)}%`} /> : dash}
        </Metric>
        <Metric label="LLM requests today">{stats ? <CountUp value={stats.requestsToday} /> : dash}</Metric>
        <Metric label="Active provider">
          {stats ? (
            <span key={active?.id ?? "none"} className="hero-in inline-block font-mono text-xl">
              {active?.label ?? "none"}
            </span>
          ) : (
            dash
          )}
        </Metric>
      </div>
    </div>
  );
}
