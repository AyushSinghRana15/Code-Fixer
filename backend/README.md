# Code Fixer — backend

The agent harness: orchestrator, agents, free-LLM router, tools and sandboxes. See the [main README](../README.md) for the overview and diagrams, and [Plan.md](../Plan.md) for the design.

```bash
uv sync
cp .env.example .env               # add at least one key
uv run fixer providers test
uv run fixer run --repo PATH --issue "bug report text"   # or --issue-file
uv run fixer fix https://github.com/owner/repo/issues/12  # or owner/repo#12: clone → fix → draft PR
uv run fixer serve                 # API for the dashboard on 127.0.0.1:8000 (docs at /api/docs)
uv run pytest                      # tests (scripted models and fake APIs, no network calls)
```

Useful `fixer run` options:

| Option | Default | What it does |
|---|---|---|
| `--scouts auto\|always\|never` | `auto` | parallel LLM scouts; `auto` runs them only when the code-built context pack is weak |
| `--candidates N` | one per provider (max 2) | fixer agents racing in separate sandboxes |
| `--stagger N` | `5` | backup fixers start after the first has used N turns without a verified fix (`0` = all at once) |
| `--provider ID` | all with keys | use only one provider |
| `--max-requests N` | `60` | LLM request budget for the job |
| `--sandbox local\|docker` | `local` | where tests run (Docker isolates; local doesn't) |
| `--apply` | off | apply the verified patch to your repo |
| `--public` | off | allow providers that train on prompts (public repos only) |

`fixer fix` also takes `--no-pr` (just produce the patch), `--ready` (open a ready-for-review PR instead of a draft) and `--comment-on-failure` (post the agent's findings on the issue if it can't fix it). Private repos are never sent to providers that train on prompts.

**API server** (`fixer/api/`): REST + Server-Sent Events for the dashboard, the contract in [docs/frontend.md §6](../docs/frontend.md), plus `POST /api/jobs` to start a job (`{"issue": "owner/repo#12"}` or `{"repoPath", "issueText"}`). It only answers requests addressed to localhost and rejects state changes from other origins.

**Storage** (`~/.fixer/fixer.db`, mode 0600, shared by the CLI and the API): jobs, per-day usage per provider, persisted provider status, and the vault (provider settings + AES-256-GCM ciphertext; master key in the OS keychain or from `FIXER_VAULT_PASSPHRASE`).

Each run writes `~/.fixer/runs/<job>/`: `events.jsonl` (full trajectory, keys redacted), `result.json` (per-agent requests and tokens), `fix.patch`, and the workspace copies.
