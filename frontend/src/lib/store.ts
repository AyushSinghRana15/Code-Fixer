// One client-side store shared by every page: loaded once, then kept current by
// the live event stream and by the results of provider/GitHub mutations.

import { api, type NewProvider } from "@/lib/api/client";
import { connectEvents, type StreamStatus } from "@/lib/sse/event-stream";
import type { GithubCredential, Job, Provider, SseEvent, StatsSummary } from "@/types";

export interface AppState {
  jobs: Job[] | null;
  stats: StatsSummary | null;
  providers: Provider[] | null;
  github: GithubCredential | null;
  stream: StreamStatus;
  loadError: string | null;
}

export const initialState: AppState = {
  jobs: null,
  stats: null,
  providers: null,
  github: null,
  stream: "connecting",
  loadError: null,
};

let state = initialState;
const listeners = new Set<() => void>();

function set(patch: Partial<AppState>) {
  state = { ...state, ...patch };
  listeners.forEach((fn) => fn());
}

export function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export const getState = () => state;

function apply(e: SseEvent) {
  switch (e.type) {
    case "job.created":
      set({ jobs: state.jobs && [e.job, ...state.jobs] });
      break;
    case "job.updated":
      set({ jobs: state.jobs?.map((j) => (j.id === e.job.id ? e.job : j)) ?? null });
      break;
    case "job.provider_switched":
      set({
        jobs:
          state.jobs?.map((j) =>
            j.id === e.jobId ? { ...j, provider: e.switch.to, switches: [...j.switches, e.switch] } : j,
          ) ?? null,
      });
      break;
    case "provider.status_changed": {
      const list = state.providers ?? [];
      const exists = list.some((p) => p.id === e.provider.id);
      set({
        providers: exists
          ? list.map((p) => (p.id === e.provider.id ? e.provider : p))
          : [...list, e.provider],
      });
      break;
    }
    case "usage.updated":
      set({
        providers:
          state.providers?.map((p) =>
            p.id === e.providerId ? { ...p, usage: { ...p.usage, requestsToday: e.requestsToday } } : p,
          ) ?? null,
      });
      break;
    case "stats.updated":
      set({ stats: e.stats });
      break;
    case "heartbeat":
      break;
  }
}

let started = false;

/** Load initial data and open the event stream. Safe to call many times. */
export function ensureStarted() {
  if (started) return;
  started = true;
  connectEvents(apply, (stream) => set({ stream }));
  Promise.all([api.listJobs(), api.getStats(), api.listProviders(), api.getGithub()])
    .then(([jobs, stats, providers, github]) => set({ jobs, stats, providers, github }))
    .catch((err: unknown) => set({ loadError: err instanceof Error ? err.message : String(err) }));
}

// ---- mutations: each returns the server's new state and stores it ----

async function refreshStats() {
  set({ stats: await api.getStats() });
}

export const actions = {
  async addProvider(p: NewProvider) {
    set({ providers: await api.addProvider(p) });
    void refreshStats();
  },
  async setEnabled(id: string, enabled: boolean) {
    set({ providers: await api.setEnabled(id, enabled) });
    void refreshStats();
  },
  async move(id: string, delta: -1 | 1) {
    const ids = (state.providers ?? []).map((p) => p.id);
    const i = ids.indexOf(id);
    const j = i + delta;
    if (i < 0 || j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    // optimistic: reorder locally first, then confirm with the server
    const byId = new Map((state.providers ?? []).map((p) => [p.id, p]));
    set({ providers: ids.map((x) => byId.get(x)!) });
    set({ providers: await api.reorder(ids) });
    void refreshStats();
  },
  testProvider: (id: string) => api.testProvider(id),
  async rotateKey(id: string, apiKey: string) {
    set({ providers: await api.rotateKey(id, apiKey) });
    void refreshStats();
  },
  async removeProvider(id: string) {
    set({ providers: await api.removeProvider(id) });
    void refreshStats();
  },
  async setGithubToken(token: string) {
    set({ github: await api.setGithubToken(token) });
  },
  async testGithub() {
    const github = await api.testGithub();
    set({ github });
    return github;
  },
  async removeGithub() {
    set({ github: await api.removeGithub() });
  },
};
