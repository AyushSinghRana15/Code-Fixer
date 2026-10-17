"use client";

import { StatCards } from "@/components/jobs/stat-cards";
import { JobsTable } from "@/components/jobs/jobs-table";
import { useAppState } from "@/hooks/use-app-state";

export function JobsView() {
  const jobs = useAppState((s) => s.jobs);
  const stats = useAppState((s) => s.stats);
  const providers = useAppState((s) => s.providers);
  const loadError = useAppState((s) => s.loadError);

  return (
    <div className="flex flex-col gap-5">
      {loadError && (
        <div role="alert" className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          Couldn&apos;t load data: {loadError}
        </div>
      )}
      <StatCards stats={stats} providers={providers} />
      <section className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-semibold">Recent jobs</h2>
          <span className="text-xs text-muted-foreground">Click a row for details · updates live</span>
        </div>
        <JobsTable jobs={jobs} providers={providers} />
      </section>
    </div>
  );
}
