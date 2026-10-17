import Link from "next/link";
import {
  ArrowRightIcon,
  ArrowUpRightIcon,
  FlaskConicalIcon,
  LockKeyholeIcon,
  RefreshCwIcon,
  ShieldCheckIcon,
} from "lucide-react";
import { cn } from "cn";
import { buttonVariants } from "@/components/ui/button";
import { AgentRunCard } from "@/components/home/agent-run-card";
import { LiveStrip } from "@/components/home/live-strip";
import { CopyCommand, Reveal } from "@/components/home/motion";
import { ThemeToggle } from "@/components/layout/theme";
import { BrandMark, NAV_FORWARD } from "@/components/layout/transitions";

const REPO_URL = "https://github.com/AyushSinghRana15/Code-Fixer";
const RUN_CMD = "fixer run --repo owner/name --issue 123";

export function HomeNav() {
  return (
    <header className="sticky top-0 z-30 border-b border-border/60 bg-background/70 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4 md:px-6">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <BrandMark />
          Code Fixer
        </Link>
        <nav aria-label="Sections" className="hidden items-center gap-5 text-sm text-muted-foreground sm:flex">
          <a href="#how" className="transition-colors hover:text-foreground">How it works</a>
          <a href="#features" className="transition-colors hover:text-foreground">Features</a>
          <a href={REPO_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 transition-colors hover:text-foreground">
            GitHub <ArrowUpRightIcon className="size-3.5" />
          </a>
        </nav>
        <div className="ml-auto flex items-center gap-1">
          <ThemeToggle />
          <Link href="/jobs" transitionTypes={NAV_FORWARD} className={buttonVariants({ size: "sm" })}>
            Dashboard
          </Link>
        </div>
      </div>
    </header>
  );
}

const HEADLINE = ["Bugs", "in.", "Pull", "requests", "out."];

export function Hero() {
  return (
    <section className="relative isolate overflow-hidden">
      <div aria-hidden className="bg-dots absolute inset-0 -z-10" />
      <div aria-hidden className="glow absolute top-10 right-[-10%] -z-10 size-[620px] md:right-[-4%]" />

      <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 pt-16 pb-20 md:px-6 lg:grid-cols-[1.05fr_1fr] lg:pt-24 lg:pb-28">
        <div className="flex flex-col items-start gap-6">
          <span
            className="hero-in inline-flex items-center gap-2 rounded-full border bg-background/60 px-3 py-1 text-xs text-muted-foreground backdrop-blur"
            style={{ "--i": 0 } as React.CSSProperties}
          >
            <span className="size-1.5 rounded-full bg-brand" />
            Free-tier LLMs · Docker sandbox · Runs locally
          </span>

          <h1 className="text-5xl leading-[1.02] font-semibold tracking-[-0.035em] text-balance sm:text-6xl lg:text-7xl">
            {HEADLINE.map((word, i) => (
              <span key={i}>
                <span
                  className={cn("hero-in inline-block", i >= 2 && "text-muted-foreground")}
                  style={{ "--i": i + 1 } as React.CSSProperties}
                >
                  {word}
                </span>
                {i === 1 ? <br /> : " "}
              </span>
            ))}
          </h1>

          <p
            className="hero-in max-w-xl text-lg leading-relaxed text-muted-foreground"
            style={{ "--i": 7 } as React.CSSProperties}
          >
            Code Fixer reads a GitHub issue, proves the bug with a failing test, fixes it in a sandbox and opens a
            pull request once every test passes. It runs on free LLM providers and switches between them when one
            runs out.
          </p>

          <div
            className="hero-in flex w-full flex-wrap items-center gap-3"
            style={{ "--i": 8 } as React.CSSProperties}
          >
            <Link
              href="/jobs"
              transitionTypes={NAV_FORWARD}
              className={cn(buttonVariants({ size: "lg" }), "group h-10 px-4")}
            >
              Open dashboard
              <ArrowRightIcon className="transition-transform duration-300 group-hover:translate-x-0.5" />
            </Link>
            <CopyCommand command={RUN_CMD} className="max-w-full" />
          </div>
        </div>

        <div className="hero-in w-full" style={{ "--i": 5 } as React.CSSProperties}>
          <AgentRunCard />
        </div>
      </div>
    </section>
  );
}

export function LiveSection() {
  return (
    <section className="mx-auto max-w-6xl px-4 md:px-6">
      <Reveal>
        <LiveStrip />
      </Reveal>
    </section>
  );
}

const STAGES = [
  {
    name: "Prepare",
    text: "Read the issue, build a sandbox and record which tests already fail.",
    steps: ["Intake", "Env setup", "Baseline"],
  },
  {
    name: "Understand",
    text: "Write a test that fails because of the bug, then find the code behind it.",
    steps: ["Reproduce", "Localize"],
  },
  {
    name: "Fix",
    text: "Edit until the test passes with no new failures. A critic then reviews the diff.",
    steps: ["Fix loop", "Verify", "Review"],
  },
  {
    name: "Ship",
    text: "Open a pull request, act on review comments and remember what worked.",
    steps: ["Deliver", "Feedback", "Learn"],
  },
];

function SectionHeading({ eyebrow, title, text }: { eyebrow: string; title: string; text: string }) {
  return (
    <div className="flex max-w-2xl flex-col gap-3" style={{ "--i": 0 } as React.CSSProperties}>
      <span className="font-mono text-xs tracking-wider text-muted-foreground uppercase">{eyebrow}</span>
      <h2 className="text-3xl font-semibold tracking-[-0.02em] text-balance sm:text-4xl">{title}</h2>
      <p className="text-muted-foreground">{text}</p>
    </div>
  );
}

export function HowItWorks() {
  return (
    <section className="mx-auto max-w-6xl scroll-mt-20 px-4 py-24 md:px-6 md:py-32" id="how">
      <Reveal className="flex flex-col gap-14">
        <SectionHeading
          eyebrow="How it works"
          title="One rung at a time."
          text="The agent climbs a fixed ladder of steps and only moves up when the current one passes. When a check fails, it loops back instead of shipping a bad fix."
        />
        <div className="relative" style={{ "--i": 1 } as React.CSSProperties}>
          <div aria-hidden className="draw-line absolute top-[5px] right-0 left-0 hidden h-px bg-border md:block" />
          <ol className="grid gap-10 md:grid-cols-4 md:gap-6">
            {STAGES.map((stage, i) => (
              <li key={stage.name} className="relative flex flex-col gap-3">
                <span className="relative z-10 hidden size-[11px] rounded-full border-2 border-background bg-foreground outline outline-border md:block" />
                <span className="font-mono text-xs text-muted-foreground">0{i + 1}</span>
                <h3 className="text-lg font-semibold">{stage.name}</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">{stage.text}</p>
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {stage.steps.map((s) => (
                    <span key={s} className="rounded-md border px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
                      {s}
                    </span>
                  ))}
                </div>
              </li>
            ))}
          </ol>
        </div>
      </Reveal>
    </section>
  );
}

const FEATURES = [
  {
    icon: FlaskConicalIcon,
    title: "Reproduce first",
    text: "Every fix starts with a test that fails for the right reason, so “tests pass” actually means something.",
  },
  {
    icon: RefreshCwIcon,
    title: "Free models, automatic failover",
    text: "OpenRouter, NVIDIA, Gemini, Groq and more. When a key expires or a quota runs out, the next provider takes over mid-job.",
  },
  {
    icon: LockKeyholeIcon,
    title: "Keys stay locked",
    text: "Encrypted with AES-256-GCM, master key in your OS keychain. Never logged and never passed into the sandbox.",
  },
  {
    icon: ShieldCheckIcon,
    title: "Guardrails on every step",
    text: "Request and time budgets, stuck detection and a test-tampering guard. If it can't fix a bug, it tells you why.",
  },
];

export function Features() {
  return (
    <section className="border-y bg-muted/30" id="features">
      <div className="mx-auto max-w-6xl scroll-mt-20 px-4 py-24 md:px-6 md:py-32">
        <Reveal className="flex flex-col gap-12">
          <SectionHeading
            eyebrow="Features"
            title="Built to be trusted with your repo."
            text="An agent that edits code needs to be careful. These are the rules it runs by."
          />
          <div className="grid gap-px overflow-hidden rounded-2xl border bg-border sm:grid-cols-2">
            {FEATURES.map(({ icon: Icon, title, text }, i) => (
              <div
                key={title}
                className="group flex flex-col gap-3 bg-background p-6 transition-colors duration-300 hover:bg-card md:p-8"
                style={{ "--i": i + 1 } as React.CSSProperties}
              >
                <span className="grid size-9 place-items-center rounded-lg border text-muted-foreground transition-all duration-300 group-hover:-translate-y-0.5 group-hover:border-foreground/30 group-hover:text-foreground">
                  <Icon className="size-4" />
                </span>
                <h3 className="font-semibold">{title}</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">{text}</p>
              </div>
            ))}
          </div>
        </Reveal>
      </div>
    </section>
  );
}

export function FinalCta() {
  return (
    <section className="mx-auto max-w-6xl px-4 py-24 md:px-6 md:py-32">
      <Reveal className="flex flex-col items-center gap-6 text-center">
        <h2
          className="max-w-2xl text-4xl font-semibold tracking-[-0.03em] text-balance sm:text-5xl"
          style={{ "--i": 0 } as React.CSSProperties}
        >
          Add a provider. <span className="text-muted-foreground">Run your first fix.</span>
        </h2>
        <p className="max-w-md text-muted-foreground" style={{ "--i": 1 } as React.CSSProperties}>
          It takes one free API key. Everything else runs on your machine.
        </p>
        <div className="flex flex-wrap justify-center gap-3" style={{ "--i": 2 } as React.CSSProperties}>
          <Link
            href="/providers"
            transitionTypes={NAV_FORWARD}
            className={cn(buttonVariants({ size: "lg" }), "group h-10 px-4")}
          >
            Set up providers
            <ArrowRightIcon className="transition-transform duration-300 group-hover:translate-x-0.5" />
          </Link>
          <Link
            href="/jobs"
            transitionTypes={NAV_FORWARD}
            className={cn(buttonVariants({ size: "lg", variant: "outline" }), "h-10 px-4")}
          >
            Open dashboard
          </Link>
        </div>
      </Reveal>
    </section>
  );
}

export function Footer() {
  return (
    <footer className="border-t">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-6 text-xs text-muted-foreground md:px-6">
        <span>Code Fixer · v0 · local preview</span>
        <a href={REPO_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 hover:text-foreground">
          Source on GitHub <ArrowUpRightIcon className="size-3" />
        </a>
      </div>
    </footer>
  );
}
