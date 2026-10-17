"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { CheckIcon, CopyIcon } from "lucide-react";
import { toast } from "sonner";
import { cn } from "cn";

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * Fades its direct children up as they scroll into view, staggered by each child's `--i`.
 * Content that's already on screen at load is never hidden, so nothing flashes.
 */
export function Reveal({ children, className, id }: { children: React.ReactNode; className?: string; id?: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || reducedMotion()) return;
    if (el.getBoundingClientRect().top < window.innerHeight * 0.9) return;
    el.dataset.reveal = "pending";
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          el.dataset.reveal = "shown";
          io.disconnect();
        }
      },
      { rootMargin: "0px 0px -12% 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <div ref={ref} id={id} data-reveal="" className={className}>
      {children}
    </div>
  );
}

/** Animates a number from its previous value to `value`. */
export function CountUp({ value, format = (n) => Math.round(n).toLocaleString() }: { value: number; format?: (n: number) => string }) {
  const [shown, setShown] = useState(0);
  const from = useRef(0);

  useEffect(() => {
    const start = from.current;
    const t0 = performance.now();
    const dur = reducedMotion() ? 0 : 900;
    let raf = requestAnimationFrame(function step(t) {
      const p = dur ? Math.min(1, (t - t0) / dur) : 1;
      const eased = 1 - Math.pow(1 - p, 3);
      setShown(start + (value - start) * eased);
      if (p < 1) raf = requestAnimationFrame(step);
      else from.current = value;
    });
    return () => cancelAnimationFrame(raf);
  }, [value]);

  return <span className="tabular-nums">{format(shown)}</span>;
}

export function CopyCommand({ command, className }: { command: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(command);
          setCopied(true);
          setTimeout(() => setCopied(false), 1600);
        } catch {
          toast.error("Couldn't copy. Select the command and copy it manually.");
        }
      }}
      aria-label={`Copy command: ${command}`}
      className={cn(
        "group inline-flex h-10 items-center gap-3 rounded-lg border bg-background/60 px-3.5 font-mono text-sm backdrop-blur transition-colors hover:border-foreground/25",
        className,
      )}
    >
      <span className="text-muted-foreground select-none">$</span>
      <span className="truncate">{command}</span>
      <span className="relative size-4 shrink-0 text-muted-foreground">
        <CopyIcon className={cn("absolute inset-0 size-4 transition-all duration-300", copied && "scale-50 opacity-0")} />
        <CheckIcon className={cn("absolute inset-0 size-4 text-foreground transition-all duration-300", !copied && "scale-50 opacity-0")} />
      </span>
    </button>
  );
}
