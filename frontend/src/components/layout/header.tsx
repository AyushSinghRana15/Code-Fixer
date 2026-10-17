"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Loader2Icon } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { StatusDot } from "@/components/ui/status-pill";
import { ThemeToggle } from "@/components/layout/theme";
import { pageTitle } from "@/components/layout/nav";
import { useAppState } from "@/hooks/use-app-state";
import { API_MODE } from "@/lib/api/client";
import type { Tone } from "@/lib/constants";

function ProviderHealth() {
  const providers = useAppState((s) => s.providers);
  if (!providers) return null;

  const active = providers.filter((p) => p.state === "active");
  const primary = providers.find((p) => p.state !== "disabled");
  let tone: Tone = "danger";
  let text = "No provider is usable. Jobs will pause until one recovers.";
  if (primary?.state === "active") {
    tone = "success";
    text = `Using ${primary.label}. ${active.length - 1} fallback${active.length === 2 ? "" : "s"} ready.`;
  } else if (active.length) {
    tone = "warning";
    text = `${primary?.label ?? "Primary"} is unavailable. Running on fallback ${active[0].label}.`;
  }

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Link
            href="/providers"
            aria-label={`Provider health: ${text}`}
            className="flex items-center gap-2 rounded-lg px-2 py-1 text-sm text-muted-foreground hover:bg-muted"
          />
        }
      >
        <StatusDot tone={tone} />
        <span className="hidden sm:inline">
          {active.length} provider{active.length === 1 ? "" : "s"} ready
        </span>
      </TooltipTrigger>
      <TooltipContent>{text}</TooltipContent>
    </Tooltip>
  );
}

export function Header() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b bg-background/85 px-4 backdrop-blur md:px-6">
      <h1 className="text-base font-semibold">{pageTitle(pathname)}</h1>
      {API_MODE === "mock" && (
        <span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">Mock data</span>
      )}
      <div className="ml-auto flex items-center gap-1">
        <ProviderHealth />
        <ThemeToggle />
      </div>
    </header>
  );
}

export function ConnectionBanner() {
  const stream = useAppState((s) => s.stream);
  if (stream !== "reconnecting") return null;
  return (
    <div role="status" className="flex items-center gap-2 bg-warning/15 px-4 py-1.5 text-sm text-warning md:px-6">
      <Loader2Icon className="size-4 animate-spin" />
      Lost the live connection. Reconnecting…
    </div>
  );
}
