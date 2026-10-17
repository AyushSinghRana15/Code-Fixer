import type { JobStatus, PhaseKey, ProviderPreset, ProviderState } from "@/types";

export const PHASES: { key: PhaseKey; label: string }[] = [
  { key: "intake", label: "Intake" },
  { key: "env", label: "Env" },
  { key: "baseline", label: "Baseline" },
  { key: "context", label: "Context" },
  { key: "reproduce", label: "Reproduce" },
  { key: "localize", label: "Localize" },
  { key: "fix", label: "Fix loop" },
  { key: "verify", label: "Verify" },
  { key: "review", label: "Review" },
  { key: "deliver", label: "Deliver" },
];

export const PHASE_LABEL = Object.fromEntries(PHASES.map((p) => [p.key, p.label])) as Record<
  PhaseKey,
  string
>;

// tone maps to the semantic colors in globals.css
export type Tone = "success" | "warning" | "danger" | "info" | "muted";

export const JOB_STATUS: Record<JobStatus, { label: string; tone: Tone }> = {
  queued: { label: "Queued", tone: "muted" },
  running: { label: "Running", tone: "info" },
  fixed: { label: "Fixed", tone: "success" },
  needs_review: { label: "Needs review", tone: "warning" },
  paused: { label: "Paused", tone: "warning" },
  pr_opened: { label: "PR opened", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
  gave_up: { label: "Gave up", tone: "warning" },
  cancelled: { label: "Cancelled", tone: "muted" },
};

export const PROVIDER_STATE: Record<ProviderState, { label: string; tone: Tone }> = {
  active: { label: "Active", tone: "success" },
  rate_limited: { label: "Rate limited", tone: "warning" },
  quota_exhausted: { label: "Quota used up", tone: "warning" },
  invalid_key: { label: "Invalid key", tone: "danger" },
  out_of_credits: { label: "Out of credits", tone: "danger" },
  disabled: { label: "Disabled", tone: "muted" },
};

export const PRESETS: ProviderPreset[] = [
  {
    id: "openrouter",
    name: "OpenRouter",
    note: "Many free models behind one key. 1,000 free requests/day after a one-time $10 top-up.",
    keyUrl: "https://openrouter.ai/keys",
    keyPrefix: "sk-or-",
    needsKey: true,
    needsBaseUrl: false,
    trainsOnData: false,
    dailyLimit: 1000,
    defaultModels: {
      fix: "nvidia/nemotron-3-super-120b-a12b:free",
      critic: "google/gemma-4-31b-it:free",
      summarize: "google/gemma-4-26b-a4b-it:free",
    },
  },
  {
    id: "nvidia",
    name: "NVIDIA API Catalog",
    note: "DeepSeek, Kimi and Nemotron models. Free for prototyping and testing.",
    keyUrl: "https://build.nvidia.com",
    keyPrefix: "nvapi-",
    needsKey: true,
    needsBaseUrl: false,
    trainsOnData: false,
    defaultModels: {
      fix: "deepseek-ai/deepseek-v4-pro",
      critic: "moonshotai/kimi-k3",
      summarize: "nvidia/nemotron-3-nano",
    },
  },
  {
    id: "gemini",
    name: "Google AI Studio",
    note: "Gemini Flash models. Free tier trains on prompts, so it's used for public repos only.",
    keyUrl: "https://aistudio.google.com/apikey",
    keyPrefix: "AIza",
    needsKey: true,
    needsBaseUrl: false,
    trainsOnData: true,
    dailyLimit: 1500,
    defaultModels: { fix: "gemini-3-flash", critic: "gemini-3-flash", summarize: "gemini-3-flash-lite" },
  },
  {
    id: "groq",
    name: "Groq",
    note: "Very fast, but an 8K tokens/minute cap. Best for small tasks like summaries.",
    keyUrl: "https://console.groq.com/keys",
    keyPrefix: "gsk_",
    needsKey: true,
    needsBaseUrl: false,
    trainsOnData: false,
    dailyLimit: 1000,
    defaultModels: { fix: "openai/gpt-oss-120b", critic: "openai/gpt-oss-120b", summarize: "openai/gpt-oss-20b" },
  },
  {
    id: "mistral",
    name: "Mistral",
    note: "About $10/month of free credits. Trains on data unless you opt out.",
    keyUrl: "https://console.mistral.ai/api-keys",
    needsKey: true,
    needsBaseUrl: false,
    trainsOnData: true,
    defaultModels: { fix: "codestral-latest", critic: "mistral-large-latest", summarize: "mistral-small-latest" },
  },
  {
    id: "ollama",
    name: "Ollama (local)",
    note: "Runs on your machine, no key and no limits. Small models only on 16 GB of RAM.",
    needsKey: false,
    needsBaseUrl: true,
    trainsOnData: false,
    defaultModels: { fix: "qwen3:8b", critic: "qwen3:8b", summarize: "qwen3:4b" },
  },
  {
    id: "anthropic",
    name: "Anthropic (paid)",
    note: "Optional paid escalation for bugs the free models can't solve.",
    keyUrl: "https://console.anthropic.com",
    keyPrefix: "sk-ant-",
    needsKey: true,
    needsBaseUrl: false,
    trainsOnData: false,
    defaultModels: { fix: "claude-opus-5-5", critic: "claude-sonnet-5-5", summarize: "claude-haiku-4-5" },
  },
  {
    id: "custom",
    name: "Custom (OpenAI-compatible)",
    note: "Any service with an OpenAI-compatible API. Bring the base URL and model names.",
    needsKey: true,
    needsBaseUrl: true,
    trainsOnData: false,
    defaultModels: { fix: "", critic: "", summarize: "" },
  },
];

export const PRESET_BY_ID = Object.fromEntries(PRESETS.map((p) => [p.id, p])) as Record<
  ProviderPreset["id"],
  ProviderPreset
>;
