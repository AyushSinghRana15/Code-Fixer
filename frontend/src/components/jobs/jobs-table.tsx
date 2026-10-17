"use client";

import { Fragment, useState } from "react";
import { ChevronRightIcon, CopyIcon, ExternalLinkIcon, TerminalIcon } from "lucide-react";
import { toast } from "sonner";
import { cn } from "cn";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { JobDetails } from "@/components/jobs/job-details";
import { useNow } from "@/hooks/use-now";
import { JOB_STATUS, PHASE_LABEL } from "@/lib/constants";
import { duration, fullTime, relativeTime } from "@/lib/format";
import type { Job, Provider } from "@/types";

const START_CMD = "fixer run --repo owner/name --issue 123";

function EmptyState() {
  return (
    <Card className="items-center gap-3 py-12 text-center">
      <TerminalIcon className="size-6 text-muted-foreground" />
      <div className="font-medium">No jobs yet</div>
      <p className="text-sm text-muted-foreground">Start one from the terminal:</p>
      <button
        type="button"
        onClick={() => navigator.clipboard.writeText(START_CMD).then(() => toast.success("Command copied"))}
        className="inline-flex items-center gap-2 rounded-lg border bg-muted/50 px-3 py-1.5 font-mono text-sm hover:bg-muted"
      >
        {START_CMD} <CopyIcon className="size-3.5 text-muted-foreground" />
      </button>
    </Card>
  );
}

function elapsed(job: Job, now: number | null) {
  if (job.status === "queued" || !now) return "—";
  const end = job.finishedAt ? Date.parse(job.finishedAt) : now;
  return duration(end - Date.parse(job.startedAt));
}

export function JobsTable({ jobs, providers }: { jobs: Job[] | null; providers: Provider[] | null }) {
  const now = useNow();
  const [open, setOpen] = useState<Set<string>>(new Set());

  if (!jobs) {
    return (
      <Card className="gap-2 px-4">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-9" />
        ))}
      </Card>
    );
  }
  if (!jobs.length) return <EmptyState />;

  const label = (id: string) => providers?.find((p) => p.id === id)?.label ?? id;
  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <Card className="py-0">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-[132px] pl-4">Status</TableHead>
            <TableHead>Issue</TableHead>
            <TableHead className="hidden xl:table-cell">Phase</TableHead>
            <TableHead className="hidden xl:table-cell">Provider</TableHead>
            <TableHead className="hidden text-right lg:table-cell">Requests</TableHead>
            <TableHead className="hidden text-right lg:table-cell">Time</TableHead>
            <TableHead className="hidden text-right sm:table-cell">Started</TableHead>
            <TableHead className="w-[64px] pr-4 text-right">PR</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {jobs.map((job) => {
            const s = JOB_STATUS[job.status];
            const expanded = open.has(job.id);
            const detailsId = `job-details-${job.id}`;
            return (
              <Fragment key={job.id}>
                <TableRow
                  onClick={() => toggle(job.id)}
                  className={cn("cursor-pointer", expanded && "border-b-0 bg-muted/40")}
                >
                  <TableCell className="pl-4">
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        aria-expanded={expanded}
                        aria-controls={detailsId}
                        aria-label={`${expanded ? "Hide" : "Show"} details for ${job.repo}${job.issueNumber ? ` #${job.issueNumber}` : ""}: ${job.issueTitle}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          toggle(job.id);
                        }}
                        className="-ml-1 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                      >
                        <ChevronRightIcon className={cn("size-4 transition-transform", expanded && "rotate-90")} />
                      </button>
                      <StatusPill tone={s.tone} pulse={job.status === "running"}>
                        {s.label}
                      </StatusPill>
                    </div>
                  </TableCell>
                  <TableCell className="max-w-[180px] sm:max-w-[320px]">
                    <div className="truncate font-mono text-xs text-muted-foreground">{job.repo}</div>
                    <div className="truncate">
                      {job.issueNumber > 0 && <span className="text-muted-foreground">#{job.issueNumber} </span>}
                      {job.issueTitle}
                    </div>
                  </TableCell>
                  <TableCell className="hidden xl:table-cell">
                    {["pr_opened", "queued", "fixed"].includes(job.status) ? (
                      <span className="text-muted-foreground">{job.status === "queued" ? "Waiting" : "Done"}</span>
                    ) : (
                      PHASE_LABEL[job.phase]
                    )}
                  </TableCell>
                  <TableCell className="hidden font-mono text-xs xl:table-cell">{label(job.provider)}</TableCell>
                  <TableCell className="hidden text-right tabular-nums lg:table-cell">
                    {job.requests}
                    <span className="text-muted-foreground">/{job.requestBudget}</span>
                  </TableCell>
                  <TableCell className="hidden text-right tabular-nums lg:table-cell">{elapsed(job, now)}</TableCell>
                  <TableCell className="hidden text-right whitespace-nowrap text-muted-foreground sm:table-cell">
                    {now ? (
                      <Tooltip>
                        <TooltipTrigger render={<span />}>{relativeTime(job.startedAt, now)}</TooltipTrigger>
                        <TooltipContent>{fullTime(job.startedAt)}</TooltipContent>
                      </Tooltip>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell className="pr-4 text-right">
                    {job.prUrl ? (
                      <a
                        href={job.prUrl}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="inline-flex items-center gap-1 text-sm font-medium text-success hover:underline"
                      >
                        PR <ExternalLinkIcon className="size-3.5" />
                      </a>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                </TableRow>
                {expanded && (
                  <TableRow id={detailsId} className="bg-muted/40 hover:bg-muted/40">
                    <TableCell colSpan={8} className="px-4 pt-1 pb-4 whitespace-normal">
                      <JobDetails job={job} providerLabel={label} />
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            );
          })}
        </TableBody>
      </Table>
    </Card>
  );
}
