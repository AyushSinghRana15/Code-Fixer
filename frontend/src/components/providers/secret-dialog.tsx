"use client";

import { useState } from "react";
import { Loader2Icon } from "lucide-react";
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
import { Label } from "@/components/ui/label";
import { KeyInput } from "@/components/providers/key-input";

/** Dialog that collects one secret (API key or token), submits it, and always clears it afterwards. */
export function SecretDialog({
  trigger,
  triggerContent,
  title,
  description,
  fieldLabel,
  placeholder,
  submitLabel,
  onSubmit,
}: {
  trigger: React.ReactElement;
  triggerContent: React.ReactNode;
  title: string;
  description: string;
  fieldLabel: string;
  placeholder?: string;
  submitLabel: string;
  onSubmit: (secret: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function close(o: boolean) {
    setOpen(o);
    if (!o) {
      setValue("");
      setError(null);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSubmit(value);
      close(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setValue("");
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogTrigger render={trigger}>{triggerContent}</DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="secret">{fieldLabel}</Label>
            <KeyInput
              id="secret"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder={placeholder}
              aria-invalid={!!error}
              required
              autoFocus
            />
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => close(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving && <Loader2Icon className="animate-spin" />}
              {saving ? "Checking…" : submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Small yes/no confirmation for destructive actions. Pass `trigger` to open it from a button,
 *  or control it with `open`/`onOpenChange` (e.g. from a menu item). */
export function ConfirmDialog({
  trigger,
  triggerContent,
  open: openProp,
  onOpenChange: onOpenChangeProp,
  title,
  description,
  confirmLabel,
  onConfirm,
}: {
  trigger?: React.ReactElement;
  triggerContent?: React.ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  onConfirm: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [openState, setOpenState] = useState(false);
  const open = openProp ?? openState;
  const onOpenChange = onOpenChangeProp ?? setOpenState;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {trigger && <DialogTrigger render={trigger}>{triggerContent}</DialogTrigger>}
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm();
                onOpenChange(false);
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy && <Loader2Icon className="animate-spin" />}
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
