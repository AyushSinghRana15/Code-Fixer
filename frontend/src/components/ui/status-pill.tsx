import { cn } from "cn";
import type { Tone } from "@/lib/constants";

const TONE: Record<Tone, { pill: string; dot: string }> = {
  success: { pill: "bg-success/12 text-success", dot: "bg-success" },
  warning: { pill: "bg-warning/14 text-warning", dot: "bg-warning" },
  danger: { pill: "bg-destructive/12 text-destructive", dot: "bg-destructive" },
  info: { pill: "bg-info/12 text-info", dot: "bg-info" },
  muted: { pill: "bg-muted text-muted-foreground", dot: "bg-muted-foreground/60" },
};

export function StatusDot({ tone, pulse, className }: { tone: Tone; pulse?: boolean; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("inline-block size-2 shrink-0 rounded-full", TONE[tone].dot, pulse && "animate-live", className)}
    />
  );
}

export function StatusPill({
  tone,
  pulse,
  children,
  className,
}: {
  tone: Tone;
  pulse?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium whitespace-nowrap",
        TONE[tone].pill,
        className,
      )}
    >
      <StatusDot tone={tone} pulse={pulse} />
      {children}
    </span>
  );
}
