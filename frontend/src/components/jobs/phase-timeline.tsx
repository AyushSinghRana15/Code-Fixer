import { CheckIcon, XIcon } from "lucide-react";
import { cn } from "cn";
import { PHASES } from "@/lib/constants";
import type { Job } from "@/types";

export function PhaseTimeline({ job }: { job: Job }) {
  return (
    <ol className="flex flex-wrap items-center gap-x-1 gap-y-2" aria-label="Pipeline phases">
      {PHASES.map(({ key, label }, i) => {
        const state = job.phases[key];
        return (
          <li key={key} className="flex items-center gap-1">
            {i > 0 && (
              <span aria-hidden className={cn("h-px w-3", state === "pending" ? "bg-border" : "bg-muted-foreground/40")} />
            )}
            <span
              className={cn(
                "inline-flex h-6 items-center gap-1 rounded-full border px-2 text-xs",
                state === "done" && "border-success/30 bg-success/10 text-success",
                state === "running" && "border-info/40 bg-info/10 text-info",
                state === "failed" && "border-destructive/40 bg-destructive/10 text-destructive",
                state === "pending" && "border-dashed text-muted-foreground",
              )}
            >
              {state === "done" && <CheckIcon className="size-3" />}
              {state === "failed" && <XIcon className="size-3" />}
              {state === "running" && <span className="size-1.5 rounded-full bg-info animate-live" />}
              {label}
              <span className="sr-only">: {state}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
