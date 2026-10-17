# Code Fixer Agent

An autonomous agent that connects to GitHub repos, reproduces reported bugs in a sandbox, fixes them, runs the tests until they pass, and opens a pull request explaining the fix. It's designed to run **nearly free** on free-tier LLM providers.

> **Status:** phase 01 (Frontend) is done: the dashboard runs on mock data (`cd frontend && npm install && npm run dev`). Phase 02 (Backend) is next. See [Plan.md](Plan.md) for the full design and decisions.

## Build roadmap

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/build-roadmap-dark.svg">
    <img src="docs/assets/build-roadmap-light.svg" alt="Build roadmap: 10 engineering phases from Frontend to Cost Optimization, each showing its status" width="820">
  </picture>
</p>

Each rung is a milestone. The ladder is updated as phases are finished.

## How the agent works

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/harness-ladder-dark.svg">
    <img src="docs/assets/harness-ladder-light.svg" alt="Agent runtime ladder: 11 steps from Intake to Learn, with loops back to the Fix step when Verify, Review or Feedback fail" width="900">
  </picture>
</p>

For every bug, the agent climbs these steps one at a time and only moves up when the current step passes. When a check fails, it loops back down (A–D) instead of shipping a bad fix. Steps marked **code** use no LLM requests, which keeps the agent within free-tier limits.

<details>
<summary><b>Loops and guardrails</b></summary>

| Loop | From → To | When |
|---|---|---|
| A | Verify → Fix loop | The full suite shows new failures |
| B | Review → Fix loop | The critic or the test-tamper guard rejects the diff |
| C | Feedback → Fix loop | A reviewer comments, or CI goes red on the PR |
| D | Fix loop → Localize | Stuck: the same failure repeats N times |

On every step: request and time budgets, stuck detection, automatic provider failover, and a written report if the agent gives up.
</details>

## Project layout

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/project-layout-dark.svg">
    <img src="docs/assets/project-layout-light.svg" alt="Project layout: Next.js frontend talking to the Python backend over REST and live events; backend modules grouped into Interface, Agent core, Models and keys, Execution, Knowledge and Quality" width="900">
  </picture>
</p>

<details>
<summary><b>Folder tree</b></summary>

```
frontend/src/        Next.js dashboard
  app/jobs/          Jobs dashboard
  app/providers/     Providers & keys
  components/        UI + shadcn/ui
  hooks/             data + live stream
  lib/               API + SSE client
  types/             shared types
backend/fixer/       Python agent
  api/  cli/                          interface
  orchestrator/  agent/  tools/       agent core
  llm/  vault/                        models & keys
  sandbox/  github/                   execution
  store/  memory/  observability/     knowledge
  guards/  evals/                     quality
backend/tests/       unit + integration tests
docs/                plan, frontend design, diagrams
deploy/              Docker, compose, CI
```
</details>

## Planned features

- CLI first: `fixer run --repo owner/name --issue 123`
- Supports Python, JavaScript/TypeScript and Java repos
- A Docker sandbox per job, with no network during test runs and no secrets inside the container
- **Multiple free LLM providers:** OpenRouter, Gemini, NVIDIA, Groq, Mistral, Ollama, or any OpenAI-compatible endpoint. You choose the primary provider and the fallback order. If a key expires, credits run out or a daily quota is hit, the agent switches to the next provider automatically, even mid-job.
- **Secure key vault:** API keys are stored encrypted (AES-256-GCM) in a local SQLite DB, with the master key in your OS keychain. Keys are never logged and never passed into the sandbox.
- **Local web dashboard** (Next.js): live jobs view and a page to manage providers and keys
- Budgets on LLM requests, iterations and time, plus stuck detection
- Full trajectory logs so every run can be replayed
- Later: a GitHub App with webhook triggers, a PR review-comment loop and parallel candidate fixes

## Requirements (planned)

- Python 3.12+
- Docker (on macOS: `brew install colima docker && colima start`)
- A GitHub token with repo access
- At least one free LLM API key (OpenRouter recommended)

## Managing providers (planned)

```bash
fixer providers add openrouter        # prompts for the key, validates it, stores it encrypted
fixer providers add nvidia
fixer providers order openrouter nvidia gemini   # primary first, then fallbacks
fixer providers list                  # status, masked keys, today's usage
fixer providers rotate-key openrouter # replace an expired key
```

## Docs

- [Plan.md](Plan.md): architecture, pipeline, LLM provider research, features, roadmap
- [docs/frontend.md](docs/frontend.md): frontend design, wireframes and the API it needs
- Diagrams are generated by [`docs/assets/build_diagrams.py`](docs/assets/build_diagrams.py). Edit the lists at the top of that file and re-run it.
