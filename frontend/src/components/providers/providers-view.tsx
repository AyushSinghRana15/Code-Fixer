"use client";

import { ShieldCheckIcon } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { AddProviderDialog } from "@/components/providers/add-provider-dialog";
import { GithubCard } from "@/components/providers/github-card";
import { ProviderCard } from "@/components/providers/provider-card";
import { useAppState } from "@/hooks/use-app-state";
import { useNow } from "@/hooks/use-now";

export function ProvidersView() {
  const providers = useAppState((s) => s.providers);
  const github = useAppState((s) => s.github);
  const now = useNow();

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">LLM providers</h2>
            <p className="text-sm text-muted-foreground">
              Order is the fallback order. The agent uses the first active provider and switches automatically when
              one fails.
            </p>
          </div>
          <AddProviderDialog />
        </div>

        {!providers ? (
          Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-[150px] rounded-xl" />)
        ) : providers.length ? (
          providers.map((p, i) => (
            <ProviderCard key={p.id} provider={p} index={i} count={providers.length} now={now} />
          ))
        ) : (
          <div className="rounded-xl border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
            No providers yet. Add one to let the agent run. OpenRouter is a good first choice.
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold">GitHub</h2>
        <GithubCard github={github} now={now} />
      </section>

      <p className="flex items-start gap-2 text-xs text-muted-foreground">
        <ShieldCheckIcon className="mt-px size-4 shrink-0" />
        Keys are write-only: they&apos;re encrypted in the local vault and this page only ever sees a masked hint.
      </p>
    </div>
  );
}
