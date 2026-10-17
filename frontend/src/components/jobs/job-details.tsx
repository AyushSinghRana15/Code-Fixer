"use client";

import { ArrowRightIcon, CopyIcon, ExternalLinkIcon } from "lucide-react";
import { toast } from "sonner";
import { PhaseTimeline } from "@/components/jobs/phase-timeline";
import { clockTime } from "@/lib/format";
import type { Job } from "@/types";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[96px_1fr] sm:gap-3">
      <dt className="text-xs font-medium text-muted-foreground sm:pt-0.5">{label}</dt>
      <dd className="min-w-0 text-sm">{children}</dd>
    </div>
  );
}

function tests(job: Job) {
  const t = job.tests;
  if (!t) return <span className="text-muted-foreground">Not run yet</span>;
  const repro = {
    not_written: "not written",
    failing: "written, fails as expected",
    passing: "now passes",
  }[t.repro];
  return (
    <div className="flex flex-col gap-0.5">
      <span>
        Baseline: {t.baselinePassed} passed
        {t.baselineFailing > 0 && <span className="text-muted-foreground">, {t.baselineFailing} already failing</span>}
      </span>
      <span>Repro test: {repro}</span>
      {t.final && (
        <span>
          Final suite: {t.final.passed} passed, {t.final.failed} failing
          {t.final.failed <= t.baselineFailing && <span className="text-success"> · no new failures</span>}
        </span>
      )}
    </div>
  );
}

export function JobDetails({ job, providerLabel }: { job: Job; providerLabel: (id: string) => string }) {
  async function copyPath() {
    try {
      await navigator.clipboard.writeText(job.trajectoryPath);
      toast.success("Path copied");
    } catch {
      toast.error("Couldn't copy. Select the path and copy it manually.");
    }
  }

  return (
    <dl className="flex flex-col gap-3 py-1">
      <Row label="Phases">
        <PhaseTimeline job={job} />
      </Row>
      {job.reason && (
        <Row label="Reason">
          <span className={job.status === "cancelled" ? "" : "text-destructive"}>{job.reason}</span>
        </Row>
      )}
      <Row label="Switches">
        {job.switches.length ? (
          <ul className="flex flex-col gap-0.5">
            {job.switches.map((s) => (
              <li key={s.at} className="flex flex-wrap items-center gap-1.5">
                <span className="text-muted-foreground tabular-nums">{clockTime(s.at)}</span>
                <span className="font-mono">{providerLabel(s.from)}</span>
                <ArrowRightIcon className="size-3.5 text-muted-foreground" />
                <span className="font-mono">{providerLabel(s.to)}</span>
                <span className="text-muted-foreground">({s.reason})</span>
              </li>
            ))}
          </ul>
        ) : (
          <span className="text-muted-foreground">None. Stayed on {providerLabel(job.provider)}.</span>
        )}
      </Row>
      <Row label="Tests">{tests(job)}</Row>
      <Row label="Links">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <a href={job.issueUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline-offset-4 hover:underline">
            Issue #{job.issueNumber} <ExternalLinkIcon className="size-3.5" />
          </a>
          {job.prUrl && (
            <a href={job.prUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline-offset-4 hover:underline">
              Pull request <ExternalLinkIcon className="size-3.5" />
            </a>
          )}
          <button
            type="button"
            onClick={copyPath}
            className="inline-flex items-center gap-1 font-mono text-xs text-muted-foreground hover:text-foreground"
            aria-label={`Copy trajectory log path ${job.trajectoryPath}`}
          >
            {job.trajectoryPath} <CopyIcon className="size-3" />
          </button>
        </div>
      </Row>
    </dl>
  );
}
