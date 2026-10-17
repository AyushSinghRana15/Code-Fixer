# Code Fixer Agent

An autonomous agent that connects to GitHub repos, reproduces reported bugs in a sandbox, fixes them, runs the tests until they pass, and opens a pull request explaining the fix. It's designed to run **nearly free** on free-tier LLM providers.

> **Status:** planning. Nothing is runnable yet. See [Plan.md](Plan.md) for the full design, decisions and milestones.

## How it works

1. **Intake:** read the GitHub issue, stack traces and CI logs.
2. **Set up:** clone the repo into a Docker sandbox, detect the stack and install dependencies.
3. **Baseline:** run the existing tests to record what already fails.
4. **Reproduce:** write a test that fails because of the bug.
5. **Fix:** locate the cause, edit the code and rerun the tests until the new test passes.
6. **Verify:** run the full suite, linter and type-check, with no new failures allowed.
7. **Review:** a critic pass checks the diff, and a guard rejects any changes that weaken existing tests.
8. **Deliver:** open a PR with the root cause, the fix and the test results.

## Planned features

- CLI first: `fixer run --repo owner/name --issue 123`
- Supports Python, JavaScript/TypeScript and Java repos
- A Docker sandbox per job, with no network during test runs and no secrets inside the container
- An LLM router across free providers (OpenRouter, Gemini, NVIDIA, Groq, Mistral, Ollama, or any OpenAI-compatible endpoint) with quota tracking
- **Multiple providers:** choose your primary provider and fallback order. If a key expires, credits run out or a daily quota is hit, the agent switches to the next provider automatically, even mid-job.
- **Secure key vault:** API keys are stored encrypted (AES-256-GCM) in a local SQLite DB, with the master key in your OS keychain. Keys are never logged and never passed into the sandbox.
- Budgets on LLM requests, iterations and time, plus stuck detection
- Full trajectory logs so every run can be replayed
- **Local web dashboard** (Next.js): live jobs view and a page to manage providers and keys
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

## Project layout

```
backend/
  fixer/
    api/          # FastAPI REST + live event stream for the UI
    cli/          # `fixer` command
    orchestrator/ # pipeline state machine, budgets
    agent/        # agent loop, prompts, context management
    llm/          # provider catalog, router, quotas, failover
    vault/        # encrypted API key storage
    tools/        # file, search, edit, test tools
    sandbox/      # Docker lifecycle, env detection
    github/       # PRs, comments, webhooks
    guards/       # test-tampering and safety checks
    store/        # job store, trajectory logs, DB
    evals/        # benchmark runner
  tests/
frontend/         # Next.js + Tailwind + shadcn/ui dashboard
docs/             # design docs
```

## Docs

- [Plan.md](Plan.md): architecture, pipeline, LLM provider research, features, milestones
- [docs/frontend.md](docs/frontend.md): frontend design, wireframes and the API it needs
