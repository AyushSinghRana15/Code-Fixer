export function relativeTime(isoTime: string, now: number): string {
  const s = Math.round((now - Date.parse(isoTime)) / 1000);
  const future = s < 0;
  const a = Math.abs(s);
  let text: string;
  if (a < 45) text = future ? "in a few seconds" : "just now";
  else if (a < 3600) text = `${Math.round(a / 60)}m`;
  else if (a < 86400) text = `${Math.round(a / 3600)}h`;
  else text = `${Math.round(a / 86400)}d`;
  if (a < 45) return text;
  return future ? `in ${text}` : `${text} ago`;
}

export function duration(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h) return `${h}h ${String(m).padStart(2, "0")}m`;
  return `${m}m ${String(sec).padStart(2, "0")}s`;
}

export const fullTime = (isoTime: string) =>
  new Date(isoTime).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

export const clockTime = (isoTime: string) =>
  new Date(isoTime).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

export const pct = (n: number) => `${Math.round(n * 100)}%`;
