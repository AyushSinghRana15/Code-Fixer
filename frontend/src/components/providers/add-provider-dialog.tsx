"use client";

import { useState } from "react";
import { ArrowLeftIcon, ExternalLinkIcon, Loader2Icon, PlusIcon, TriangleAlertIcon } from "lucide-react";
import { toast } from "sonner";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { KeyInput } from "@/components/providers/key-input";
import { PRESETS, PRESET_BY_ID } from "@/lib/constants";
import { actions } from "@/lib/store";
import type { ModelRoles, PresetId } from "@/types";

export function AddProviderDialog() {
  const [open, setOpen] = useState(false);
  const [preset, setPreset] = useState<PresetId | null>(null);
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [models, setModels] = useState<ModelRoles>({ fix: "", critic: "", summarize: "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setPreset(null);
    setLabel("");
    setApiKey("");
    setBaseUrl("");
    setModels({ fix: "", critic: "", summarize: "" });
    setError(null);
  }

  function choose(id: PresetId) {
    setPreset(id);
    setError(null);
    if (id === "ollama") setBaseUrl("http://localhost:11434/v1");
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!preset) return;
    setSaving(true);
    setError(null);
    try {
      await actions.addProvider({
        preset,
        label: label || undefined,
        apiKey: apiKey || undefined,
        baseUrl: baseUrl || undefined,
        models: preset === "custom" ? models : undefined,
      });
      toast.success(`${PRESET_BY_ID[preset].name} added`, { description: "Key validated and stored encrypted." });
      setOpen(false);
      reset();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setApiKey(""); // never keep a key around after a submit
      setSaving(false);
    }
  }

  const p = preset ? PRESET_BY_ID[preset] : null;

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) reset();
      }}
    >
      <DialogTrigger render={<Button />}>
        <PlusIcon /> Add provider
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        {!p ? (
          <>
            <DialogHeader>
              <DialogTitle>Add an LLM provider</DialogTitle>
              <DialogDescription>Pick a service. You can add as many as you like; they become fallbacks in order.</DialogDescription>
            </DialogHeader>
            <div className="grid max-h-[60vh] gap-2 overflow-y-auto sm:grid-cols-2">
              {PRESETS.map((x) => (
                <button
                  key={x.id}
                  type="button"
                  onClick={() => choose(x.id)}
                  className="flex flex-col gap-1 rounded-lg border p-3 text-left transition-colors hover:border-foreground/30 hover:bg-muted/50"
                >
                  <span className="flex items-center gap-2 text-sm font-medium">
                    {x.name}
                    {x.trainsOnData && (
                      <span className="rounded-full bg-warning/14 px-1.5 text-[11px] text-warning">trains on data</span>
                    )}
                  </span>
                  <span className="text-xs text-muted-foreground">{x.note}</span>
                </button>
              ))}
            </div>
          </>
        ) : (
          <form onSubmit={save} className="flex flex-col gap-4">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setPreset(null)}
                  aria-label="Back to provider list"
                  className="-ml-1 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  <ArrowLeftIcon className="size-4" />
                </button>
                Add {p.name}
              </DialogTitle>
              <DialogDescription>{p.note}</DialogDescription>
            </DialogHeader>

            {p.trainsOnData && (
              <div className="flex gap-2 rounded-lg bg-warning/12 px-3 py-2 text-xs text-warning">
                <TriangleAlertIcon className="mt-0.5 size-3.5 shrink-0" />
                This provider may train on your prompts, so the agent will only use it for public repos.
              </div>
            )}

            {p.needsKey && (
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between">
                  <Label htmlFor="api-key">API key</Label>
                  {p.keyUrl && (
                    <a href={p.keyUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                      Get a key <ExternalLinkIcon className="size-3" />
                    </a>
                  )}
                </div>
                <KeyInput
                  id="api-key"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={p.keyPrefix ? `${p.keyPrefix}…` : "Paste your key"}
                  aria-invalid={!!error}
                  required
                />
                <p className="text-xs text-muted-foreground">
                  Checked with a live call, then stored encrypted. It&apos;s never shown again, only a masked hint.
                </p>
              </div>
            )}

            {p.needsBaseUrl && (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="base-url">Base URL</Label>
                <Input id="base-url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.example.com/v1" className="font-mono" required />
              </div>
            )}

            {preset === "custom" && (
              <div className="grid gap-3 sm:grid-cols-3">
                {(["fix", "critic", "summarize"] as const).map((role) => (
                  <div key={role} className="flex flex-col gap-1.5">
                    <Label htmlFor={`model-${role}`} className="capitalize">{role} model</Label>
                    <Input
                      id={`model-${role}`}
                      value={models[role]}
                      onChange={(e) => setModels((m) => ({ ...m, [role]: e.target.value }))}
                      placeholder={role === "fix" ? "required" : "optional"}
                      className="font-mono"
                      required={role === "fix"}
                    />
                  </div>
                ))}
              </div>
            )}

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="label">
                Label <span className="font-normal text-muted-foreground">(optional)</span>
              </Label>
              <Input id="label" value={label} onChange={(e) => setLabel(e.target.value)} placeholder={p.id} />
            </div>

            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={saving} className={cn(saving && "cursor-wait")}>
                {saving && <Loader2Icon className="animate-spin" />}
                {saving ? "Checking key…" : "Validate & save"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
