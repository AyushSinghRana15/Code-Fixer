"use client";

import { useLayoutEffect, useSyncExternalStore } from "react";
import { MonitorIcon, MoonIcon, SunIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export type ThemePref = "system" | "light" | "dark";
const KEY = "theme";
const ORDER: ThemePref[] = ["system", "light", "dark"];

/** Runs in <head> before first paint so the page never flashes the wrong theme. */
export const themeScript = `(function(){try{var t=localStorage.getItem("${KEY}")||"system";var d=t==="dark"||(t==="system"&&matchMedia("(prefers-color-scheme: dark)").matches);var r=document.documentElement;r.classList.toggle("dark",d);r.style.colorScheme=d?"dark":"light"}catch(e){}})()`;

const listeners = new Set<() => void>();

function readPref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

function resolve(pref: ThemePref): "light" | "dark" {
  if (pref !== "system") return pref;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function apply(pref: ThemePref) {
  const dark = resolve(pref) === "dark";
  const root = document.documentElement;
  root.classList.toggle("dark", dark);
  root.style.colorScheme = dark ? "dark" : "light";
}

function setPref(pref: ThemePref) {
  try {
    localStorage.setItem(KEY, pref);
  } catch {
    // storage blocked: the theme still applies for this page view
  }
  apply(pref);
  listeners.forEach((fn) => fn());
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  const onSystem = () => {
    if (readPref() === "system") apply("system");
    fn();
  };
  mq.addEventListener("change", onSystem);
  return () => {
    listeners.delete(fn);
    mq.removeEventListener("change", onSystem);
  };
}

export function useTheme() {
  const pref = useSyncExternalStore(subscribe, readPref, () => "system" as ThemePref);
  const resolved = useSyncExternalStore(
    subscribe,
    () => resolve(readPref()),
    () => "light" as const,
  );
  return { pref, resolved, setPref };
}

const ICON = { system: MonitorIcon, light: SunIcon, dark: MoonIcon };
const LABEL = { system: "System theme", light: "Light theme", dark: "Dark theme" };

export function ThemeToggle() {
  const { pref, setPref } = useTheme();
  // React's dev-mode remount resets <html> attributes; re-apply before paint.
  useLayoutEffect(() => apply(readPref()), []);

  const next = ORDER[(ORDER.indexOf(pref) + 1) % ORDER.length];
  const Icon = ICON[pref];
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            aria-label={`${LABEL[pref]}. Switch to ${LABEL[next].toLowerCase()}`}
            onClick={() => setPref(next)}
          />
        }
      >
        <Icon />
      </TooltipTrigger>
      <TooltipContent>{LABEL[pref]} · click for {next}</TooltipContent>
    </Tooltip>
  );
}
