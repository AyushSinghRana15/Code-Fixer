"use client";

import { useEffect, useSyncExternalStore } from "react";
import { ensureStarted, getState, initialState, subscribe, type AppState } from "@/lib/store";

/** Read the shared app state. Starts loading data and the live stream on first use. */
export function useAppState<T>(select: (s: AppState) => T): T {
  useEffect(ensureStarted, []);
  return useSyncExternalStore(
    subscribe,
    () => select(getState()),
    () => select(initialState),
  );
}
