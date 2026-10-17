"use client";

import { useEffect, useState } from "react";
import { CheckIcon } from "lucide-react";
import { cn } from "cn";

type Step = { label: string; done: string; llm?: boolean; ms?: number };

// One scripted run, played on a loop. Mirrors the real pipeline in Plan.md §4.
const STEPS: Step[] = [
  { label: "Intake", done: "Task spec from the issue and stack trace", llm: true },
  { label: "Env setup", done: "Python 3.12 · pytest · deps cached", ms: 650 },
  { label: "Baseline", done: "212 passed · 2 already failing", ms: 700 },
  { label: "Reproduce", done: "test_checkout_without_billing fails ✓", llm: true, ms: 900 },
  { label: "Localize", done: "billing/address.py:88", ms: 650 },
  { label: "Fix loop", done: "2 attempts · repro test passes", llm: true },
  { label: "Verify", done: "213 passed · no new failures", ms: 800 },
  { label: "Review", done: "Critic approved · no tests weakened", llm: true },
  { label: "Deliver", done: "Pull request #143 opened", llm: true },
];
const FIX = STEPS.findIndex((s) => s.label === "Fix loop");
const ATTEMPTS = ["attempt 1 · 1 test still failing", "attempt 2 · all tests pass"];

interface RunState {
  step: number; // index of the running step; STEPS.length = finished
  attempt: number;
  requests: number;
  fading: boolean;
}
const START: RunState = { step: -1, attempt: 0, requests: 0, fading: false };
const FINISHED: RunState = { step: STEPS.length, attempt: 1, requests: 14, fading: false };

export function AgentRunCard() {
  const [s, setS] = useState<RunState>(START);

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    const at = (ms: number, fn: () => void) => timers.push(setTimeout(fn, ms));

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      at(0, () => setS(FINISHED));
      return () => timers.forEach(clearTimeout);
    }

    function play() {
      setS(START);
      let t = 500;
      STEPS.forEach((step, i) => {
        if (i === FIX) {
          at(t, () => setS((p) => ({ ...p, step: i, attempt: 0, requests: p.requests + 3 })));
          t += 1300;
          at(t, () => setS((p) => ({ ...p, attempt: 1, requests: p.requests + 2 })));
          t += 1100;
        } else {
          at(t, () => setS((p) => ({ ...p, step: i, requests: p.requests + (step.llm ? 2 : 0) })));
          t += step.ms ?? 750;
        }
      });
      at(t, () => setS((p) => ({ ...p, step: STEPS.length })));
      t += 3400;
      at(t, () => setS((p) => ({ ...p, fading: true })));
      t += 500;
      at(t, play);
    }
    at(0, play);
    return () => timers.forEach(clearTimeout);
  }, []);

  const finished = s.step >= STEPS.length;
  const doneCount = Math.max(0, Math.min(s.step, STEPS.length));
  const progress = doneCount / (STEPS.length - 1);

  return (
    <div className="relative rounded-2xl border bg-card/80 shadow-[0_1px_0_0_var(--border),0_24px_60px_-30px_color-mix(in_oklch,var(--foreground)_35%,transparent)] backdrop-blur">
      {/* window chrome */}
      <div className="flex items-center gap-3 border-b px-4 py-3">
        <div className="flex gap-1.5" aria-hidden>
          {[0, 1, 2].map((i) => (
            <span key={i} className="size-2.5 rounded-full bg-muted-foreground/25" />
          ))}
        </div>
        <div className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground">
          acme/payments-api <span className="text-foreground">#142</span> · Crash when user has no billing address
        </div>
        <span
          className={cn(
            "inline-flex h-6 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium transition-colors duration-500",
            finished ? "bg-foreground text-background" : "bg-muted text-foreground",
          )}
        >
          <span
            className={cn(
              "size-1.5 rounded-full transition-colors duration-500",
              finished ? "bg-background" : "animate-live bg-brand",
            )}
          />
          {finished ? "PR opened" : "Running"}
        </span>
      </div>

      {/* steps */}
      <ol
        aria-label="Example agent run"
        className={cn("relative px-4 py-3 transition-opacity duration-500", s.fading && "opacity-0")}
      >
        {/* rail behind the step icons; the filled part tracks progress */}
        <span aria-hidden className="absolute top-6 bottom-6 left-[27px] w-px bg-border" />
        <span
          aria-hidden
          className="absolute top-6 left-[27px] w-px bg-foreground transition-[height] duration-700 ease-out"
          style={{ height: `calc((100% - 3rem) * ${progress})` }}
        />
        {STEPS.map((step, i) => {
          const state = i < s.step || finished ? "done" : i === s.step ? "running" : "pending";
          const detail =
            state === "done" ? step.done : state === "running" ? (i === FIX ? ATTEMPTS[s.attempt] : "working…") : "";
          return (
            <li key={step.label} className="relative flex items-center gap-3 py-[5px]">
              <span className="relative z-10 grid size-6 shrink-0 place-items-center rounded-full bg-card">
                {state === "done" ? (
                  <span className="grid size-5 place-items-center rounded-full bg-foreground text-background">
                    <CheckIcon className="size-3" strokeWidth={3} />
                  </span>
                ) : state === "running" ? (
                  <span className="size-5 animate-spin rounded-full border-2 border-brand/25 border-t-brand" />
                ) : (
                  <span className="size-3 rounded-full border border-muted-foreground/40" />
                )}
              </span>
              <span
                className={cn(
                  "w-[76px] shrink-0 text-sm transition-colors duration-300",
                  state === "pending" ? "text-muted-foreground/60" : "font-medium text-foreground",
                )}
              >
                {step.label}
              </span>
              <span
                key={detail}
                className={cn(
                  "min-w-0 truncate font-mono text-xs transition-all duration-500",
                  detail ? "translate-x-0 opacity-100" : "-translate-x-1 opacity-0",
                  state === "running" && i === FIX && s.attempt === 0 ? "text-destructive" : "text-muted-foreground",
                )}
                style={{ animation: detail ? "hero-in 450ms var(--ease-out) both" : undefined }}
              >
                {detail}
              </span>
            </li>
          );
        })}
      </ol>

      {/* footer */}
      <div className="flex items-center justify-between gap-3 border-t px-4 py-2.5 font-mono text-[11px] text-muted-foreground">
        <span className="truncate">openrouter · nemotron-3-super-120b:free</span>
        <span className="shrink-0 tabular-nums">{s.requests} / 60 requests</span>
      </div>
    </div>
  );
}
