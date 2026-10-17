"use client";

import { useState } from "react";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CheckIcon,
  EllipsisIcon,
  ExternalLinkIcon,
  KeyRoundIcon,
  Loader2Icon,
  PlugZapIcon,
  PowerIcon,
  Trash2Icon,
  TriangleAlertIcon,
  XIcon,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { StatusPill } from "@/components/ui/status-pill";
import { ConfirmDialog, SecretDialog } from "@/components/providers/secret-dialog";
import { PRESET_BY_ID, PROVIDER_STATE } from "@/lib/constants";
import { clockTime, relativeTime } from "@/lib/format";
import { actions } from "@/lib/store";
import type { Provider, ProviderTestResult } from "@/types";

function UsageBar({ provider }: { provider: Provider }) {
  const { requestsToday, dailyLimit } = provider.usage;
  const ratio = dailyLimit ? Math.min(1, requestsToday / dailyLimit) : null;
  return (
    <div className="flex min-w-[180px] flex-col gap-1">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>Today</span>
        <span className="tabular-nums">
          {requestsToday.toLocaleString()} / {dailyLimit ? dailyLimit.toLocaleString() : "no fixed limit"} req
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        {ratio !== null && (
          <div
            className={cn("h-full", ratio > 0.85 ? "bg-warning" : "bg-info")}
            style={{ width: `${Math.max(ratio * 100, requestsToday ? 1 : 0)}%` }}
          />
        )}
      </div>
    </div>
  );
}

export function ProviderCard({
  provider,
  index,
  count,
  now,
}: {
  provider: Provider;
  index: number;
  count: number;
  now: number | null;
}) {
  const preset = PRESET_BY_ID[provider.preset];
  const st = PROVIDER_STATE[provider.state];
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<ProviderTestResult | null>(null);
  const [removeOpen, setRemoveOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const disabled = provider.state === "disabled";

  async function test() {
    setTesting(true);
    setResult(null);
    try {
      setResult(await actions.testProvider(provider.id));
    } catch (err) {
      setResult({ ok: false, latencyMs: 0, toolCalling: false, message: err instanceof Error ? err.message : String(err) });
    } finally {
      setTesting(false);
    }
  }

  async function run(fn: () => Promise<void>, done: string) {
    setBusy(true);
    try {
      await fn();
      toast.success(done);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const retry =
    provider.retryAt && now ? ` · retries ${relativeTime(provider.retryAt, now)} (${clockTime(provider.retryAt)})` : "";

  return (
    <Card className={cn("gap-3 px-4", disabled && "opacity-70")}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex flex-col items-center gap-0.5">
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={`Move ${provider.label} up`}
            disabled={index === 0}
            onClick={() => actions.move(provider.id, -1)}
          >
            <ArrowUpIcon />
          </Button>
          <span className="font-mono text-xs text-muted-foreground tabular-nums">{index + 1}</span>
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={`Move ${provider.label} down`}
            disabled={index === count - 1}
            onClick={() => actions.move(provider.id, 1)}
          >
            <ArrowDownIcon />
          </Button>
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm font-semibold">{provider.label}</span>
            {provider.label !== preset.name && <span className="text-xs text-muted-foreground">{preset.name}</span>}
            <StatusPill tone={st.tone}>{st.label}</StatusPill>
            {index === 0 && !disabled && (
              <span className="rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground">primary</span>
            )}
            {provider.trainsOnData && (
              <span className="inline-flex items-center gap-1 rounded-full bg-warning/14 px-2 py-0.5 text-[11px] text-warning">
                <TriangleAlertIcon className="size-3" /> trains on data · public repos only
              </span>
            )}
          </div>
          {(provider.stateReason || retry) && provider.state !== "active" && (
            <p className="text-xs text-muted-foreground">
              {provider.stateReason}
              {retry}
            </p>
          )}
          <dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-[auto_1fr]">
            <dt className="text-muted-foreground">Key</dt>
            <dd className="font-mono">{provider.keyHint ?? (preset.needsKey ? "—" : "not needed")}</dd>
            <dt className="text-muted-foreground">Fix model</dt>
            <dd className="truncate font-mono">{provider.models.fix}</dd>
            {provider.baseUrl && (
              <>
                <dt className="text-muted-foreground">Base URL</dt>
                <dd className="truncate font-mono">{provider.baseUrl}</dd>
              </>
            )}
          </dl>
        </div>

        <UsageBar provider={provider} />
      </div>

      <div className="flex flex-wrap items-center gap-2 border-t pt-3">
        <Button variant="outline" size="sm" onClick={test} disabled={testing}>
          {testing ? <Loader2Icon className="animate-spin" /> : <PlugZapIcon />} Test
        </Button>
        {preset.needsKey && (
          <SecretDialog
            trigger={<Button variant="outline" size="sm" />}
            triggerContent={
              <>
                <KeyRoundIcon /> Rotate key
              </>
            }
            title={`Rotate ${provider.label} key`}
            description="The new key is checked with a live call first. The old key is replaced only if the new one works."
            fieldLabel="New API key"
            placeholder={preset.keyPrefix ? `${preset.keyPrefix}…` : undefined}
            submitLabel="Validate & replace"
            onSubmit={async (key) => {
              await actions.rotateKey(provider.id, key);
              setResult(null);
              toast.success(`${provider.label} key replaced`, { description: "Provider is active again." });
            }}
          />
        )}
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() =>
            run(
              () => actions.setEnabled(provider.id, disabled),
              `${provider.label} ${disabled ? "enabled" : "disabled"}`,
            )
          }
        >
          <PowerIcon /> {disabled ? "Enable" : "Disable"}
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={<Button variant="ghost" size="icon-sm" aria-label={`More actions for ${provider.label}`} />}
          >
            <EllipsisIcon />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            {preset.keyUrl && (
              <DropdownMenuItem onClick={() => window.open(preset.keyUrl, "_blank", "noreferrer")}>
                <ExternalLinkIcon /> Open key settings
              </DropdownMenuItem>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onClick={() => setRemoveOpen(true)}>
              <Trash2Icon /> Remove…
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        {result && (
          <span
            role="status"
            className={cn("ml-auto inline-flex items-center gap-1 text-xs", result.ok ? "text-success" : "text-destructive")}
          >
            {result.ok ? <CheckIcon className="size-3.5" /> : <XIcon className="size-3.5" />}
            {result.message}
          </span>
        )}
      </div>

      <ConfirmDialog
        open={removeOpen}
        onOpenChange={setRemoveOpen}
        title={`Remove ${provider.label}?`}
        description="Its encrypted key is deleted from the vault. Running jobs fail over to the next provider."
        confirmLabel="Remove provider"
        onConfirm={async () => {
          await actions.removeProvider(provider.id);
          toast.success(`${provider.label} removed`);
        }}
      />
    </Card>
  );
}
