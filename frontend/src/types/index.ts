// Shared types. These mirror the backend's Pydantic models (docs/frontend.md §6.5).

export type JobStatus =
  | "queued"
  | "running"
  | "fixed"
  | "needs_review"
  | "paused"
  | "pr_opened"
  | "failed"
  | "gave_up"
  | "cancelled";

export type PhaseKey =
  | "intake"
  | "env"
  | "baseline"
  | "context"
  | "reproduce"
  | "localize"
  | "fix"
  | "verify"
  | "review"
  | "deliver";

export type PhaseState = "pending" | "running" | "done" | "failed";

export interface ProviderSwitch {
  at: string; // ISO timestamp
  from: string;
  to: string;
  reason: string;
}

export interface TestSummary {
  baselinePassed: number;
  baselineFailing: number;
  repro: "not_written" | "failing" | "passing";
  final?: { passed: number; failed: number };
}

export interface Job {
  id: string;
  repo: string; // owner/name
  issueNumber: number;
  issueTitle: string;
  issueUrl: string; // empty for local runs (fixer run)
  status: JobStatus;
  phase: PhaseKey;
  phases: Record<PhaseKey, PhaseState>;
  provider: string; // provider id currently in use
  requests: number;
  requestBudget: number;
  startedAt: string;
  finishedAt?: string;
  prUrl?: string;
  reason?: string; // why it failed / gave up / paused
  switches: ProviderSwitch[];
  tests?: TestSummary;
  trajectoryPath: string;
}

export type ProviderState =
  | "active"
  | "rate_limited"
  | "quota_exhausted"
  | "invalid_key"
  | "out_of_credits"
  | "disabled";

export type PresetId =
  | "openrouter"
  | "gemini"
  | "nvidia"
  | "groq"
  | "mistral"
  | "ollama"
  | "anthropic"
  | "custom";

export interface ModelRoles {
  fix: string;
  critic: string;
  summarize: string;
}

export interface Provider {
  id: string;
  preset: PresetId;
  label: string;
  state: ProviderState;
  stateReason?: string;
  retryAt?: string;
  keyHint?: string; // e.g. "sk-or-…a1b2". The full key never leaves the backend.
  baseUrl?: string;
  models: ModelRoles;
  trainsOnData: boolean;
  usage: { requestsToday: number; dailyLimit?: number };
  source?: "vault" | "env"; // env: key comes from backend/.env and is managed there
}

export interface ProviderPreset {
  id: PresetId;
  name: string;
  note: string;
  keyUrl?: string;
  keyPrefix?: string;
  needsKey: boolean;
  needsBaseUrl: boolean;
  trainsOnData: boolean;
  dailyLimit?: number;
  defaultModels: ModelRoles;
}

export interface GithubCredential {
  state: "valid" | "invalid" | "missing";
  keyHint?: string;
  login?: string;
  scopes: string[];
  checkedAt?: string;
  source?: "vault" | "env" | "gh";
}

export interface StatsSummary {
  jobsToday: number;
  runningNow: number;
  successRate7d: number | null; // 0..1, null when nothing finished yet
  finished7d: number;
  succeeded7d: number;
  requestsToday: number;
  capacityToday: number;
  activeProvider: string | null;
  fallbacksReady: number;
}

export interface ProviderTestResult {
  ok: boolean;
  latencyMs: number;
  toolCalling: boolean;
  message: string;
}

export type SseEvent =
  | { type: "job.created"; job: Job }
  | { type: "job.updated"; job: Job }
  | { type: "job.provider_switched"; jobId: string; switch: ProviderSwitch }
  | { type: "provider.status_changed"; provider: Provider }
  | { type: "usage.updated"; providerId: string; requestsToday: number }
  | { type: "stats.updated"; stats: StatsSummary }
  | { type: "heartbeat" };
