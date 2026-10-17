// In-browser stand-in for the FastAPI backend (v0). It keeps state in memory,
// simulates a live agent run and emits the same events the real SSE stream will.
// Only ever created on the client (from effects), never during prerendering.

import { PHASES, PRESET_BY_ID } from "@/lib/constants";
import type {
  GithubCredential,
  Job,
  ModelRoles,
  PhaseKey,
  PhaseState,
  PresetId,
  Provider,
  ProviderTestResult,
  SseEvent,
  StatsSummary,
} from "@/types";

export class ApiError extends Error {}

const MIN = 60_000;
const HOUR = 60 * MIN;
const TICK_MS = 1500;
const PHASE_TICKS: Partial<Record<PhaseKey, number>> = { fix: 8, reproduce: 4, localize: 3 };

const SAMPLE_ISSUES = [
  { repo: "acme/web-dashboard", title: "Export button downloads an empty CSV" },
  { repo: "acme/payments-api", title: "Webhook retries fire twice on timeout" },
  { repo: "acme/orders-java", title: "Pagination skips the last page" },
  { repo: "demo/cli-tools", title: "--verbose flag ignored in config file" },
];

const iso = (t: number) => new Date(t).toISOString();
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const latency = () => sleep(250 + Math.random() * 400);
const clone = <T,>(v: T): T => structuredClone(v);

function phasesUpTo(current: PhaseKey, currentState: PhaseState): Record<PhaseKey, PhaseState> {
  const idx = PHASES.findIndex((p) => p.key === current);
  return Object.fromEntries(
    PHASES.map((p, i) => [p.key, i < idx ? "done" : i === idx ? currentState : "pending"]),
  ) as Record<PhaseKey, PhaseState>;
}

export function maskKey(key: string, prefix?: string): string {
  const head = prefix && key.startsWith(prefix) ? prefix : key.slice(0, 4);
  return `${head}…${key.slice(-4)}`;
}

function validateKey(presetId: PresetId, key: string | undefined) {
  const preset = PRESET_BY_ID[presetId];
  if (!preset.needsKey) return;
  const k = (key ?? "").trim();
  if (!k) throw new ApiError("Enter an API key.");
  if (preset.keyPrefix && !k.startsWith(preset.keyPrefix))
    throw new ApiError(`This doesn't look like a ${preset.name} key (they start with "${preset.keyPrefix}").`);
  if (k.length < 16 || /invalid|bad|expired/i.test(k))
    throw new ApiError(`${preset.name} rejected the key (401). Check that you copied the whole key.`);
}

function seedJobs(now: number): Job[] {
  const base = (over: Partial<Job> & Pick<Job, "id" | "repo" | "issueNumber" | "issueTitle">): Job => ({
    issueUrl: `https://github.com/${over.repo}/issues/${over.issueNumber}`,
    status: "pr_opened",
    phase: "deliver",
    phases: phasesUpTo("deliver", "done"),
    provider: "openrouter",
    requests: 0,
    requestBudget: 60,
    startedAt: iso(now),
    switches: [],
    trajectoryPath: `~/.fixer/runs/${over.id}.json`,
    ...over,
  });

  return [
    base({
      id: "j-1042", repo: "acme/payments-api", issueNumber: 142,
      issueTitle: "Crash when user has no billing address",
      status: "running", phase: "fix", phases: phasesUpTo("fix", "running"),
      requests: 23, startedAt: iso(now - 4 * MIN),
      tests: { baselinePassed: 212, baselineFailing: 2, repro: "failing" },
    }),
    base({
      id: "j-1041", repo: "acme/web-dashboard", issueNumber: 91,
      issueTitle: "Chart tooltip shows the wrong timezone",
      status: "queued", phase: "intake", phases: phasesUpTo("intake", "pending"),
      startedAt: iso(now - 40_000),
    }),
    base({
      id: "j-1040", repo: "acme/web-dashboard", issueNumber: 88,
      issueTitle: "Date picker off by one day in March",
      provider: "nvidia", requests: 41,
      startedAt: iso(now - 75 * MIN), finishedAt: iso(now - 66 * MIN),
      prUrl: "https://github.com/acme/web-dashboard/pull/89",
      switches: [{ at: iso(now - 71 * MIN), from: "openrouter", to: "nvidia", reason: "429: 20 requests/minute limit" }],
      tests: { baselinePassed: 340, baselineFailing: 0, repro: "passing", final: { passed: 341, failed: 0 } },
    }),
    base({
      id: "j-1039", repo: "demo/cli-tools", issueNumber: 7,
      issueTitle: "Flaky import on Python 3.13",
      status: "failed", phase: "reproduce", phases: phasesUpTo("reproduce", "failed"),
      provider: "gemini", requests: 60,
      startedAt: iso(now - 3 * HOUR - 12 * MIN), finishedAt: iso(now - 3 * HOUR),
      reason: "Request budget reached (60/60). Could not write a failing test for the bug.",
      switches: [{ at: iso(now - 3 * HOUR - 5 * MIN), from: "openrouter", to: "gemini", reason: "Daily quota reached" }],
      tests: { baselinePassed: 58, baselineFailing: 1, repro: "not_written" },
    }),
    base({
      id: "j-1038", repo: "acme/payments-api", issueNumber: 137,
      issueTitle: "Refund rounding error for JPY",
      requests: 29, startedAt: iso(now - 5 * HOUR), finishedAt: iso(now - 4 * HOUR - 52 * MIN),
      prUrl: "https://github.com/acme/payments-api/pull/138",
      tests: { baselinePassed: 210, baselineFailing: 2, repro: "passing", final: { passed: 211, failed: 2 } },
    }),
    base({
      id: "j-1037", repo: "acme/search-service", issueNumber: 54,
      issueTitle: "Memory leak in result cache",
      status: "gave_up", phase: "fix", phases: phasesUpTo("fix", "failed"),
      requests: 47, startedAt: iso(now - 7 * HOUR), finishedAt: iso(now - 6 * HOUR - 41 * MIN),
      reason: "Stuck: the same test failure repeated 4 times. Likely needs a design change in CacheStore.evict().",
      tests: { baselinePassed: 96, baselineFailing: 0, repro: "failing" },
    }),
    base({
      id: "j-1036", repo: "acme/orders-java", issueNumber: 203,
      issueTitle: "NullPointerException in OrderMapper when discount is null",
      requests: 35, startedAt: iso(now - 26 * HOUR), finishedAt: iso(now - 25 * HOUR - 48 * MIN),
      prUrl: "https://github.com/acme/orders-java/pull/204",
      tests: { baselinePassed: 512, baselineFailing: 3, repro: "passing", final: { passed: 513, failed: 3 } },
    }),
    base({
      id: "j-1035", repo: "demo/cli-tools", issueNumber: 5,
      issueTitle: "Help text cut off in narrow terminals",
      status: "cancelled", phase: "baseline", phases: phasesUpTo("baseline", "failed"),
      requests: 3, startedAt: iso(now - 30 * HOUR), finishedAt: iso(now - 30 * HOUR + 2 * MIN),
      reason: "Cancelled from the CLI.",
    }),
  ];
}

function seedProviders(now: number): Provider[] {
  const p = (id: PresetId, over: Partial<Provider>): Provider => ({
    id,
    preset: id,
    label: id,
    state: "active",
    models: { ...PRESET_BY_ID[id].defaultModels },
    trainsOnData: PRESET_BY_ID[id].trainsOnData,
    usage: { requestsToday: 0, dailyLimit: PRESET_BY_ID[id].dailyLimit },
    ...over,
  });
  return [
    p("openrouter", { keyHint: "sk-or-…a1b2", usage: { requestsToday: 182, dailyLimit: 1000 } }),
    p("nvidia", {
      keyHint: "nvapi-…9f0c", state: "rate_limited", retryAt: iso(now + 90_000),
      stateReason: "429: 40 requests/minute limit reached", usage: { requestsToday: 40 },
    }),
    p("gemini", {
      keyHint: "AIza…77Qe", state: "invalid_key",
      stateReason: "Key rejected (401). Rotate the key to re-enable.", usage: { requestsToday: 12, dailyLimit: 1500 },
    }),
    p("groq", { keyHint: "gsk_…3k9d", state: "disabled", stateReason: "Disabled by you" }),
  ];
}

class MockBackend {
  private jobs: Job[];
  private providers: Provider[];
  private github: GithubCredential;
  private listeners = new Set<(e: SseEvent) => void>();
  private phaseTicks = 0;
  private idleTicks = 0;
  private nextId = 1043;

  constructor(now: number) {
    this.jobs = seedJobs(now);
    this.providers = seedProviders(now);
    this.github = {
      state: "valid", keyHint: "ghp_…77de", login: "demo-user",
      scopes: ["repo", "workflow"], checkedAt: iso(now - 10 * MIN),
    };
    setInterval(() => this.tick(), TICK_MS);
    setInterval(() => this.emit({ type: "heartbeat" }), 15_000);
  }

  // ---- events ----
  subscribe(fn: (e: SseEvent) => void) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }
  private emit(e: SseEvent) {
    const copy = clone(e);
    this.listeners.forEach((fn) => fn(copy));
  }
  private emitStats() {
    this.emit({ type: "stats.updated", stats: this.stats() });
  }

  // ---- simulation ----
  private tick() {
    const now = Date.now();
    let changed = false;

    for (const p of this.providers) {
      if (p.state === "rate_limited" && p.retryAt && Date.parse(p.retryAt) <= now) {
        p.state = "active";
        p.retryAt = undefined;
        p.stateReason = undefined;
        this.emit({ type: "provider.status_changed", provider: p });
        changed = true;
      }
    }

    const job = this.jobs.find((j) => j.status === "running");
    if (job) {
      this.advance(job, now);
      changed = true;
    } else if (this.jobs.some((j) => j.status === "queued")) {
      if (++this.idleTicks >= 3) {
        const next = [...this.jobs].reverse().find((j) => j.status === "queued")!;
        next.status = "running";
        next.phases.intake = "running";
        next.provider = this.activeProvider()?.id ?? next.provider;
        next.startedAt = iso(now);
        this.idleTicks = 0;
        this.phaseTicks = 0;
        this.emit({ type: "job.updated", job: next });
        changed = true;
      }
    } else if (++this.idleTicks >= 14) {
      const sample = SAMPLE_ISSUES[this.nextId % SAMPLE_ISSUES.length];
      const id = `j-${this.nextId++}`;
      const job: Job = {
        id, repo: sample.repo, issueNumber: 100 + (this.nextId % 200), issueTitle: sample.title,
        issueUrl: `https://github.com/${sample.repo}/issues/${100 + (this.nextId % 200)}`,
        status: "queued", phase: "intake", phases: phasesUpTo("intake", "pending"),
        provider: this.activeProvider()?.id ?? "openrouter", requests: 0, requestBudget: 60,
        startedAt: iso(now), switches: [], trajectoryPath: `~/.fixer/runs/${id}.json`,
      };
      this.jobs.unshift(job);
      this.idleTicks = 0;
      this.emit({ type: "job.created", job });
      changed = true;
    }

    if (changed) this.emitStats();
  }

  private advance(job: Job, now: number) {
    const provider = this.providers.find((p) => p.id === job.provider);
    const usesLlm = ["intake", "reproduce", "localize", "fix", "review", "deliver"].includes(job.phase);
    if (usesLlm && job.requests < job.requestBudget) {
      const n = 1 + Math.round(Math.random());
      job.requests = Math.min(job.requestBudget, job.requests + n);
      if (provider) {
        provider.usage.requestsToday += n;
        this.emit({ type: "usage.updated", providerId: provider.id, requestsToday: provider.usage.requestsToday });
      }
    }

    if (++this.phaseTicks >= (PHASE_TICKS[job.phase] ?? 2)) {
      this.phaseTicks = 0;
      job.phases[job.phase] = "done";
      if (job.phase === "baseline") job.tests = { baselinePassed: 120 + (job.issueNumber % 90), baselineFailing: job.issueNumber % 3, repro: "not_written" };
      if (job.phase === "reproduce" && job.tests) job.tests.repro = "failing";
      if (job.phase === "fix" && job.tests) job.tests.repro = "passing";
      if (job.phase === "verify" && job.tests)
        job.tests.final = { passed: job.tests.baselinePassed + 1, failed: job.tests.baselineFailing };

      const idx = PHASES.findIndex((p) => p.key === job.phase);
      if (idx === PHASES.length - 1) {
        job.status = "pr_opened";
        job.finishedAt = iso(now);
        job.prUrl = `https://github.com/${job.repo}/pull/${job.issueNumber + 1}`;
      } else {
        job.phase = PHASES[idx + 1].key;
        job.phases[job.phase] = "running";
      }
    }
    this.emit({ type: "job.updated", job });
  }

  // ---- derived ----
  private activeProvider() {
    return this.providers.find((p) => p.state === "active");
  }

  private stats(): StatsSummary {
    const now = new Date();
    const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const weekAgo = now.getTime() - 7 * 24 * HOUR;
    const finished = this.jobs.filter(
      (j) => ["pr_opened", "failed", "gave_up"].includes(j.status) && Date.parse(j.startedAt) >= weekAgo,
    );
    const succeeded = finished.filter((j) => j.status === "pr_opened").length;
    const usable = this.providers.filter((p) => p.state === "active");
    return {
      jobsToday: this.jobs.filter((j) => Date.parse(j.startedAt) >= startOfDay).length,
      runningNow: this.jobs.filter((j) => j.status === "running").length,
      successRate7d: finished.length ? succeeded / finished.length : null,
      finished7d: finished.length,
      succeeded7d: succeeded,
      requestsToday: this.providers.reduce((s, p) => s + p.usage.requestsToday, 0),
      capacityToday: this.providers
        .filter((p) => p.state !== "disabled" && p.state !== "invalid_key")
        .reduce((s, p) => s + (p.usage.dailyLimit ?? 0), 0),
      activeProvider: usable[0]?.id ?? null,
      fallbacksReady: Math.max(0, usable.length - 1),
    };
  }

  private find(id: string) {
    const p = this.providers.find((x) => x.id === id);
    if (!p) throw new ApiError("Provider not found.");
    return p;
  }

  private changedProvider(p: Provider) {
    this.emit({ type: "provider.status_changed", provider: p });
    this.emitStats();
    return clone(this.providers);
  }

  // ---- API surface (mirrors docs/frontend.md §6.1) ----
  async listJobs() {
    await latency();
    return clone([...this.jobs].sort((a, b) => Date.parse(b.startedAt) - Date.parse(a.startedAt)));
  }
  async getStats() {
    await latency();
    return this.stats();
  }
  async listProviders() {
    await latency();
    return clone(this.providers);
  }

  async addProvider(input: { preset: PresetId; label?: string; apiKey?: string; baseUrl?: string; models?: ModelRoles }) {
    await sleep(700); // live key check
    const preset = PRESET_BY_ID[input.preset];
    validateKey(input.preset, input.apiKey);
    if (preset.needsBaseUrl && !input.baseUrl?.trim() && input.preset !== "ollama")
      throw new ApiError("Enter the service's base URL.");
    const models = input.models ?? preset.defaultModels;
    if (!models.fix.trim()) throw new ApiError("Enter at least the model to use for fixing.");

    let id: string = input.preset;
    for (let n = 2; this.providers.some((p) => p.id === id); n++) id = `${input.preset}-${n}`;
    const provider: Provider = {
      id, preset: input.preset, label: input.label?.trim() || id, state: "active",
      keyHint: input.apiKey ? maskKey(input.apiKey.trim(), preset.keyPrefix) : undefined,
      baseUrl: input.baseUrl?.trim() || (input.preset === "ollama" ? "http://localhost:11434/v1" : undefined),
      models: { ...models }, trainsOnData: preset.trainsOnData,
      usage: { requestsToday: 0, dailyLimit: preset.dailyLimit },
    };
    this.providers.push(provider);
    return this.changedProvider(provider);
  }

  async setEnabled(id: string, enabled: boolean) {
    await latency();
    const p = this.find(id);
    if (enabled && p.state === "disabled") {
      p.state = "active";
      p.stateReason = undefined;
    } else if (!enabled) {
      p.state = "disabled";
      p.stateReason = "Disabled by you";
      p.retryAt = undefined;
    }
    return this.changedProvider(p);
  }

  async reorder(ids: string[]) {
    await sleep(150);
    this.providers.sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id));
    this.emitStats();
    return clone(this.providers);
  }

  async testProvider(id: string): Promise<ProviderTestResult> {
    await sleep(600 + Math.random() * 600);
    const p = this.find(id);
    if (p.state === "invalid_key")
      return { ok: false, latencyMs: 210, toolCalling: false, message: "401 Unauthorized: the key was rejected." };
    if (p.state === "out_of_credits")
      return { ok: false, latencyMs: 240, toolCalling: false, message: "402: no credits left on this account." };
    const ms = Math.round(300 + Math.random() * 600);
    return { ok: true, latencyMs: ms, toolCalling: true, message: `Key valid · 3 models reachable · tool calling works (${ms} ms)` };
  }

  async rotateKey(id: string, apiKey: string) {
    await sleep(700);
    const p = this.find(id);
    validateKey(p.preset, apiKey);
    p.keyHint = maskKey(apiKey.trim(), PRESET_BY_ID[p.preset].keyPrefix);
    p.state = "active";
    p.stateReason = undefined;
    p.retryAt = undefined;
    return this.changedProvider(p);
  }

  async removeProvider(id: string) {
    await latency();
    this.find(id);
    this.providers = this.providers.filter((p) => p.id !== id);
    this.emitStats();
    return clone(this.providers);
  }

  async getGithub() {
    await latency();
    return clone(this.github);
  }

  async setGithubToken(token: string) {
    await sleep(700);
    const t = token.trim();
    if (!/^(ghp_|github_pat_)/.test(t)) throw new ApiError('GitHub tokens start with "ghp_" or "github_pat_".');
    if (t.length < 20 || /invalid|bad|expired/i.test(t)) throw new ApiError("GitHub rejected the token (401).");
    this.github = {
      state: "valid", keyHint: maskKey(t, t.startsWith("ghp_") ? "ghp_" : "github_pat_"),
      login: "demo-user", scopes: ["repo", "workflow"], checkedAt: iso(Date.now()),
    };
    return clone(this.github);
  }

  async testGithub() {
    await sleep(600);
    if (this.github.state !== "missing") this.github.checkedAt = iso(Date.now());
    return clone(this.github);
  }

  async removeGithub() {
    await latency();
    this.github = { state: "missing", scopes: [] };
    return clone(this.github);
  }
}

let instance: MockBackend | null = null;

export function getMockBackend() {
  if (typeof window === "undefined") throw new Error("The mock backend only runs in the browser.");
  instance ??= new MockBackend(Date.now());
  return instance;
}
