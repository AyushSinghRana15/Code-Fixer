"use client";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusDot } from "@/components/ui/status-pill";
import { pct } from "@/lib/format";
import type { Provider, StatsSummary } from "@/types";

function Stat({ label, value, sub, children }: { label: string; value: React.ReactNode; sub: React.ReactNode; children?: React.ReactNode }) {
  return (
    <Card className="gap-1.5 px-4">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="text-2xl font-semibold tracking-tight tabular-nums">{value}</div>
      {children}
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">{sub}</div>
    </Card>
  );
}

export function StatCards({ stats, providers }: { stats: StatsSummary | null; providers: Provider[] | null }) {
  if (!stats || !providers) {
    return (
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-[104px] rounded-xl" />
        ))}
      </div>
    );
  }

  const active = providers.find((p) => p.id === stats.activeProvider);
  const used = stats.capacityToday ? Math.min(1, stats.requestsToday / stats.capacityToday) : 0;

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Stat
        label="Jobs today"
        value={stats.jobsToday}
        sub={
          stats.runningNow ? (
            <>
              <StatusDot tone="info" pulse /> {stats.runningNow} running
            </>
          ) : (
            "None running"
          )
        }
      />
      <Stat
        label="Success rate · 7 days"
        value={stats.successRate7d === null ? "—" : pct(stats.successRate7d)}
        sub={`${stats.succeeded7d} of ${stats.finished7d} finished jobs were fixed`}
      />
      <Stat
        label="LLM requests today"
        value={
          <>
            {stats.requestsToday.toLocaleString()}
            <span className="text-base font-normal text-muted-foreground">
              {" "}/ {stats.capacityToday.toLocaleString()}
            </span>
          </>
        }
        sub="across all providers with a known daily limit"
      >
        <div
          className="h-1.5 overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-label="Requests used today"
          aria-valuenow={Math.round(used * 100)}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className={used > 0.85 ? "h-full bg-warning" : "h-full bg-info"}
            style={{ width: `${Math.max(used * 100, 1)}%` }}
          />
        </div>
      </Stat>
      <Stat
        label="Active provider"
        value={<span className="font-mono text-xl">{active?.label ?? "None"}</span>}
        sub={
          active ? (
            <>
              <StatusDot tone="success" /> {stats.fallbacksReady} fallback{stats.fallbacksReady === 1 ? "" : "s"} ready
            </>
          ) : (
            <>
              <StatusDot tone="danger" /> Jobs pause until a provider recovers
            </>
          )
        }
      />
    </div>
  );
}
