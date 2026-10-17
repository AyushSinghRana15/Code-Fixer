// Live event stream (docs/frontend.md §6.2). Each SSE message's data is a JSON
// SseEvent with a "type" field. EventSource reconnects on its own; we only
// report the connection status so the UI can show a "Reconnecting…" banner.

import { API_MODE } from "@/lib/api/client";
import { getMockBackend } from "@/lib/api/mock-backend";
import type { SseEvent } from "@/types";

export type StreamStatus = "connecting" | "live" | "reconnecting";

export function connectEvents(
  onEvent: (e: SseEvent) => void,
  onStatus: (s: StreamStatus) => void,
): () => void {
  if (API_MODE === "mock") {
    onStatus("live");
    return getMockBackend().subscribe(onEvent);
  }

  onStatus("connecting");
  const es = new EventSource("/api/events");
  es.onopen = () => onStatus("live");
  es.onerror = () => onStatus("reconnecting");
  es.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data) as SseEvent);
    } catch {
      // ignore malformed messages
    }
  };
  return () => es.close();
}
