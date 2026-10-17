# Frontend Design (v0)

> A simple first version, upgraded step by step. This doc also lists the backend features and API the frontend needs (§6), so the backend can be built against it.
> Last updated: 2026-10-17

## 1. Decisions

| Topic | Decision |
|---|---|
| Stack | **Next.js (App Router) + TypeScript + Tailwind** |
| Components | **shadcn/ui**, "base-nova" style built on **Base UI** (copied into `src/components/ui`). Dialogs/menus/tooltips use the `render` prop instead of Radix's `asChild` |
| Theme | **Dark + light**, follows the system setting, with a manual toggle. Done with an inline `<head>` script (Next.js 16 guide), not `next-themes` |
| Users | **Single user, local only**: runs on localhost, no login |
| Live updates | **Server-Sent Events (SSE)** from the backend |
| v0 pages | **Home** (`/`), **Jobs dashboard** and **Providers & keys** |
| Motion | React `<ViewTransition>` route transitions (no animation library): directional slide home ↔ dashboard, logo morph, crossfade between dashboard pages. All motion respects `prefers-reduced-motion` |
| Palette | Minimal: neutrals plus one accent (`--brand`), with semantic colors only for statuses |
| Starting jobs | CLI only in v0 (`fixer run ...`); the UI shows them live |
| GitHub token | Managed on the Providers & keys page, stored in the same encrypted vault |

## 2. Home page (`/`)

A minimal landing page with its own top nav (no sidebar):

1. **Hero:** "Bugs in. Pull requests out." with a staggered blur-in, the run command (click to copy), and an **animated agent-run card** that loops through the pipeline: steps check off, the first fix attempt fails, the second passes, and the status flips to "PR opened".
2. **Live strip:** jobs today, success rate, requests today and active provider from the same live store as the dashboard, with count-up numbers.
3. **How it works:** the four stages (Prepare, Understand, Fix, Ship) revealed on scroll, with a line drawing across.
4. **Features:** reproduce first, free models with failover, locked keys, guardrails.
5. **Call to action** to set up providers, then a footer.

## 2b. Dashboard layout

```
┌────────────┬───────────────────────────────────────────────────────────┐
│ ⚙ Fixer    │  Jobs                                   ● 3 providers  ◐  │  ← header: page title,
│            ├───────────────────────────────────────────────────────────┤     provider health dot,
│ ▸ Jobs     │                                                           │     theme toggle
│ ▸ Providers│                    (page content)                         │
│   & keys   │                                                           │
│            │                                                           │
│            │                                                           │
└────────────┴───────────────────────────────────────────────────────────┘
   sidebar
```

- **Sidebar:** Jobs, Providers & keys. Later pages get added here.
- **Header health dot:** green when at least one provider is active, amber when only fallbacks are left, red when nothing is usable. Clicking it opens Providers & keys.
- On mobile the sidebar collapses into a menu button.

## 3. Page: Jobs dashboard (`/jobs`, also `/`)

```
┌──────────────┬──────────────┬──────────────────┬──────────────────┐
│ Jobs today   │ Success rate │ LLM requests     │ Active provider  │
│ 4            │ 67% (7 days) │ 182 / 1,000      │ openrouter       │
│ 1 running    │ 6 of 9       │ ▓▓▓░░░░░░░ today │ 2 fallbacks ready│
└──────────────┴──────────────┴──────────────────┴──────────────────┘

 Status       Repo               Issue                      Phase      Provider    Req  Time   Started
 ─────────────────────────────────────────────────────────────────────────────────────────────────────
 ● Running    acme/api           #142 Null user crash        Fix loop   openrouter   23  4m12  2m ago
 ✓ PR opened  acme/web           #88  Date off by one        Done       nvidia       41  9m03  1h ago   ↗ PR
 ▾ ✗ Failed   me/tools           #7   Flaky import           Reproduce  gemini       60  12m    3h ago
   ┌──────────────────────────────────────────────────────────────────────────────────────────┐
   │ Phases  ✓ Intake ✓ Env ✓ Baseline ✗ Reproduce · Localize · Fix · Verify · Review · Deliver│
   │ Reason  Request budget reached (60/60). Could not write a failing test for the bug.       │
   │ Switches 10:42 openrouter → gemini (daily quota reached)                                   │
   │ Tests   Baseline: 212 passed, 2 already failing                                            │
   │ Links   Issue ↗   Trajectory log: ~/.fixer/runs/7f3a.json                                  │
   └──────────────────────────────────────────────────────────────────────────────────────────┘
```

**Summary cards**
1. Jobs today, plus how many are running.
2. Success rate over 7 days: PRs opened ÷ finished jobs.
3. LLM requests today against the combined daily capacity of all active providers.
4. Active provider (the current primary), plus the number of fallbacks ready.

**Jobs table**
- Columns: status badge, repo, issue number and title, current phase, current provider, requests used, duration, started (relative time), PR link.
- Status badges: `queued`, `running`, `paused` (all providers down), `pr_opened`, `failed`, `gave_up`, `cancelled`.
- Newest first, 50 per page.

**Expandable row** (click a row)
- A timeline of the 9 pipeline phases, each done, running, failed or not reached.
- Failure or give-up reason.
- Provider switches during the job, with the time and reason.
- Test summary: baseline counts, plus the repro test result and the final full-suite result.
- Links to the issue and PR, and the path of the trajectory log file.

**Live behaviour (SSE)**
- New jobs appear at the top. Status, phase, requests and duration update in place, and the stat cards refresh.
- Running jobs get a subtle pulse on their status badge.
- If the event stream drops, a small "Reconnecting…" banner shows while it reconnects automatically.

**Empty state:** "No jobs yet. Start one from the terminal:" followed by a copyable `fixer run --repo owner/name --issue 123`.

## 4. Page: Providers & keys (`/providers`)

```
 LLM providers                                                  [+ Add provider]
 Order = fallback order. The first active provider is used.
 ┌───────────────────────────────────────────────────────────────────────────┐
 │ 1 ▲▼  openrouter        ● Active          sk-or-…a1b2                       │
 │       fix: nemotron-3-super-120b:free     Today ▓▓▓░░░░░ 182 / 1,000 req     │
 │                                           [Test] [Rotate key] [Disable] [⋯] │
 ├───────────────────────────────────────────────────────────────────────────┤
 │ 2 ▲▼  nvidia            ● Rate limited until 10:58   nvapi-…9f0c             │
 │       fix: deepseek-v4-pro                Today ▓░░░░░░░  40 / —            │
 ├───────────────────────────────────────────────────────────────────────────┤
 │ 3 ▲▼  gemini  ⚠ trains on data (public repos only)   ● Invalid key           │
 │       → "Key rejected (401) at 09:14. Rotate the key to re-enable."          │
 └───────────────────────────────────────────────────────────────────────────┘

 GitHub
 ┌───────────────────────────────────────────────────────────────────────────┐
 │ Token  ghp_…77de   ● Valid   Signed in as @AyushSinghRana15                  │
 │ Scopes: repo, workflow                         [Test] [Rotate] [Remove]     │
 └───────────────────────────────────────────────────────────────────────────┘
```

**Provider list**
- Order sets the fallback order. v0 uses ▲▼ buttons; drag-and-drop comes later.
- Each card shows:
  - the preset name or custom label
  - a status badge (`active`, `rate_limited`, `quota_exhausted`, `invalid_key`, `out_of_credits`, `disabled`), with `retry_at` when there is one
  - the masked key hint
  - the model per role
  - a bar of today's usage against the known limit
  - a ⚠ "trains on data" warning where it applies
- Actions:
  - **Test:** a live check that the key is valid, the models are reachable and tool calling works
  - **Rotate key**, **Enable/Disable**
  - **⋯ menu:** edit models, remove (with confirmation)

**Add provider dialog**
1. Pick a preset (OpenRouter, Gemini, NVIDIA, Groq, Mistral, Ollama, Anthropic, Custom). Each preset shows a short note and a link to get a key.
2. Enter the API key in a password field, with an optional label. Custom presets also need `base_url` and the model names.
3. On Save, the backend validates the key. Valid keys are encrypted and stored, and the dialog closes. Invalid keys show an inline error and nothing is saved.

**GitHub section:** one token, with the same Test / Rotate / Remove actions. The test shows the account login and the token's scopes, and warns if `repo` is missing.

**Security rules in the UI**
- Keys are **write-only**. The API never returns a full key, only the hint (`sk-or-…a1b2`).
- The key input is cleared after submit and never kept in state, localStorage or the URL.
- No key ever appears in toasts, errors or console logs.

## 5. Theme and style
- shadcn/ui defaults with a neutral palette and one accent color, plus semantic colors for statuses: green = success/active, amber = rate-limited/paused, red = failed/invalid, blue = running.
- An inline script handles system, light and dark before first paint, with the toggle in the header (cycles system → light → dark).
- Times shown relative ("2m ago"), with the full timestamp on hover. Monospace for repo names, key hints and paths.

## 6. What the backend provides (implemented in `backend/fixer/api/`)

Implemented as designed, with these additions: job statuses `fixed` (local runs, no PR) and `needs_review`; a `context` phase; `source` on providers (`vault` | `env`; env providers are read-only in the UI) and on the GitHub credential (`vault` | `env` | `gh`); `POST /api/jobs` to start a job; `GET /api/health`. The SSE stream is produced by polling the shared SQLite store once a second, so jobs started from the CLI appear too.

### 6.1 REST API (FastAPI, `backend/fixer/api/`)

| Method & path | Purpose |
|---|---|
| `GET /api/stats/summary` | Data for the four stat cards |
| `GET /api/jobs?limit=50&cursor=` | Jobs list (newest first) |
| `GET /api/jobs/{id}` | Expanded row: phases, reason, provider switches, test summary, links |
| `GET /api/events` | **SSE stream** of live events (§6.2) |
| `GET /api/providers` | Providers with status, `retry_at`, key hint, models, today's usage, limits |
| `GET /api/providers/presets` | Preset catalog for the Add dialog |
| `POST /api/providers` | Add a provider (validates the key, then saves it encrypted) |
| `PATCH /api/providers/{id}` | Enable/disable, edit models or label |
| `PUT /api/providers/order` | Save the fallback order (`[id, ...]`) |
| `POST /api/providers/{id}/test` | Live check of key, models and tool calling |
| `PUT /api/providers/{id}/key` | Rotate the key (validate, then replace) |
| `DELETE /api/providers/{id}` | Remove a provider and its key |
| `GET /api/credentials/github` | Token hint, login, scopes, status |
| `PUT /api/credentials/github` | Set or rotate the token (validates it against GitHub) |
| `POST /api/credentials/github/test` | Re-check the token |
| `DELETE /api/credentials/github` | Remove the token |

### 6.2 SSE events (`GET /api/events`)

| Event | Payload | Used by |
|---|---|---|
| `job.created` | Job summary | Jobs table |
| `job.updated` | id, status, phase, provider, requests, duration, pr_url | Jobs table, expanded row |
| `job.provider_switched` | id, from, to, reason, at | Expanded row |
| `provider.status_changed` | id, state, reason, retry_at | Providers page, header dot |
| `usage.updated` | provider_id, requests_today | Providers usage bars, stat card |
| `stats.updated` | Summary object | Stat cards |
| `heartbeat` | every 15s | Detecting a dropped connection |

### 6.3 Backend features this implies
- **Job store** (`store/`): jobs with per-phase status, timestamps, reason, request count, provider switches and test summaries.
- **Event bus** (`api/`): the orchestrator and router publish events, and the SSE endpoint streams them. The CLI process and the API server share state through the SQLite DB. The API watches for changes, or the CLI posts events to the API when it's running.
- **Usage aggregation** (`llm/`): requests per provider per day, plus known daily limits for the capacity numbers.
- **Provider status machine** (`llm/`): the states from Plan §7.5, with `retry_at` and the reason.
- **Key validation** (`vault/` + `llm/`): a cheap live call before saving, with a separate GitHub token check for login and scopes.

### 6.4 Local-only security (no login, but still protected)
- The API binds to **127.0.0.1 only**.
- Next.js proxies `/api/*` to the backend (`rewrites`), so the browser sees a single origin and no CORS is needed.
- The backend rejects requests whose `Host` isn't `localhost`/`127.0.0.1`, which blocks DNS-rebinding attacks.
- It also rejects state-changing requests whose `Origin` isn't the frontend's, so other websites open in the browser can't call the local API.

### 6.5 Shared types (`frontend/src/types/`)
`Job`, `JobPhase`, `JobStatus`, `ProviderSwitch`, `TestSummary`, `Provider`, `ProviderState`, `ProviderPreset`, `GithubCredential`, `StatsSummary`, `SseEvent`. These mirror the backend's Pydantic models. Later they can be generated from FastAPI's OpenAPI schema.

## 7. Folder map

```
frontend/
  public/
  src/
    app/
      jobs/            # Jobs dashboard page (/ redirects here)
      providers/       # Providers & keys page
    components/
      ui/              # shadcn/ui components
      layout/          # sidebar, header, theme toggle, health dot
      jobs/            # stat cards, jobs table, expandable row, phase timeline
      providers/       # provider card, add/rotate dialogs, GitHub card
    hooks/             # useEventStream, useJobs, useProviders
    lib/
      api/             # typed fetch client for /api/*
      sse/             # EventSource wrapper with auto-reconnect
    types/             # shared TS types
```

## 8. Roadmap

| Version | Adds |
|---|---|
| **v0** | Jobs dashboard (stats + expandable rows, live) and Providers & keys (incl. GitHub token) |
| v1 | Job detail page (`/jobs/[id]`) with a live agent step log, diff viewer and test output; New job form; cancel/retry; filters and search |
| v2 | Repositories page (connected repos, `.fixer.yml` settings); Evals page (model comparison); Settings (budgets, defaults); drag-to-reorder providers |
| v3 | Multi-user with GitHub login, per-user vaults, GitHub App installation flow |
