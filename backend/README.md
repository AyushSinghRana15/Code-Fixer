# Code Fixer — backend

The agent harness: orchestrator, agents, free-LLM router, tools and sandboxes. See the [main README](../README.md) for the overview and diagrams, and [Plan.md](../Plan.md) for the design.

```bash
uv sync
cp .env.example .env               # add at least one key
uv run fixer providers test
uv run fixer run --repo PATH --issue "bug report text"   # or --issue-file
uv run pytest                      # harness tests (scripted models, no API calls)
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

Each run writes `~/.fixer/runs/<job>/`: `events.jsonl` (full trajectory, keys redacted), `result.json` (per-agent requests and tokens), `fix.patch`, and the workspace copies.
