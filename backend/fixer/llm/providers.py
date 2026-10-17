"""Provider catalog (Plan.md §7.1). Every entry speaks the OpenAI-compatible chat API.

Free model lists change often. Model ids marked "check" weren't verifiable when this was written;
run `fixer providers test` to see what works, and override with FIXER_<ID>_MODEL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

ROLES = ("fix", "critic", "summarize", "scout")

# Roles that should go to a particular provider first. Scouts are small, read-only and latency-bound,
# so they suit Groq's fast small models (and keep the main provider's quota for the expensive agents).
ROLE_PREFERENCE: dict[str, tuple[str, ...]] = {"scout": ("groq", "openrouter")}


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    name: str
    base_url: str
    key_envs: tuple[str, ...]  # first one that is set wins
    models: dict[str, tuple[str, ...]] = field(default_factory=dict)  # role -> fallback list
    rpm: int | None = None  # requests/minute on the free tier; the router paces to stay under it
    trains_on_data: bool = False  # never used for private repos
    needs_key: bool = True


_OR_FIX = (
    "nvidia/nemotron-3-super-120b-a12b:free",
    "poolside/laguna-s-2.1:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
)

CATALOG: dict[str, ProviderSpec] = {
    "openrouter": ProviderSpec(
        id="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        key_envs=("FIXER_OPENROUTER_API_KEY", "OPENROUTER_API_KEY"),
        models={
            "fix": _OR_FIX,
            "critic": _OR_FIX,
            "summarize": ("google/gemma-4-26b-a4b-it:free", *_OR_FIX),
            "scout": ("google/gemma-4-26b-a4b-it:free", "nvidia/nemotron-3-super-120b-a12b:free"),
        },
        rpm=20,
    ),
    "nvidia": ProviderSpec(
        id="nvidia",
        name="NVIDIA API Catalog",
        base_url="https://integrate.api.nvidia.com/v1",
        key_envs=("FIXER_NVIDIA_API_KEY", "NVIDIA_API_KEY"),
        models={  # check
            "fix": ("deepseek-ai/deepseek-v4-pro", "moonshotai/kimi-k3"),
            "critic": ("moonshotai/kimi-k3", "deepseek-ai/deepseek-v4-pro"),
            "summarize": ("deepseek-ai/deepseek-v4-flash",),
        },
        rpm=40,
    ),
    "groq": ProviderSpec(
        id="groq",
        name="Groq",
        base_url="https://api.groq.com/openai/v1",
        key_envs=("FIXER_GROQ_API_KEY", "GROQ_API_KEY"),
        models={
            "fix": ("openai/gpt-oss-120b",),
            "critic": ("openai/gpt-oss-120b",),
            "summarize": ("openai/gpt-oss-20b",),
            "scout": ("openai/gpt-oss-20b", "openai/gpt-oss-120b"),
        },
        rpm=30,
    ),
    "gemini": ProviderSpec(
        id="gemini",
        name="Google AI Studio",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        key_envs=("FIXER_GEMINI_API_KEY", "GEMINI_API_KEY"),
        models={
            "fix": ("gemini-3-flash",),
            "critic": ("gemini-3-flash",),
            "summarize": ("gemini-3-flash-lite",),
        },  # check
        rpm=10,
        trains_on_data=True,
    ),
    "mistral": ProviderSpec(
        id="mistral",
        name="Mistral",
        base_url="https://api.mistral.ai/v1",
        key_envs=("FIXER_MISTRAL_API_KEY", "MISTRAL_API_KEY"),
        models={
            "fix": ("codestral-latest", "mistral-large-latest"),
            "critic": ("mistral-large-latest",),
            "summarize": ("mistral-small-latest",),
        },
        trains_on_data=True,
    ),
    "ollama": ProviderSpec(
        id="ollama",
        name="Ollama (local)",
        base_url="http://localhost:11434/v1",
        key_envs=(),
        models={"fix": ("qwen3:8b",), "critic": ("qwen3:8b",), "summarize": ("qwen3:4b",)},
        needs_key=False,
    ),
}

DEFAULT_ORDER = ("openrouter", "nvidia", "groq", "gemini", "mistral")


def models_for(spec: ProviderSpec, role: str) -> tuple[str, ...]:
    """Role's model list, with FIXER_<ID>_MODEL (all roles) or FIXER_<ID>_<ROLE>_MODEL put first."""
    base = spec.models.get(role) or spec.models.get("fix", ())
    override = os.environ.get(f"FIXER_{spec.id.upper()}_{role.upper()}_MODEL") or os.environ.get(
        f"FIXER_{spec.id.upper()}_MODEL"
    )
    if override:
        return (override, *[m for m in base if m != override])
    return base


def key_for(spec: ProviderSpec) -> str | None:
    for name in spec.key_envs:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def configured() -> list[tuple[ProviderSpec, str | None]]:
    """Providers that can be used right now, in FIXER_PROVIDERS order."""
    order = [p.strip() for p in os.environ.get("FIXER_PROVIDERS", ",".join(DEFAULT_ORDER)).split(",") if p.strip()]
    if os.environ.get("FIXER_OLLAMA_MODEL") and "ollama" not in order:
        order.append("ollama")
    out = []
    for pid in order:
        spec = CATALOG.get(pid)
        if not spec:
            continue
        key = key_for(spec)
        if spec.needs_key and not key:
            continue
        out.append((spec, key))
    return out


def mask(key: str | None) -> str:
    if not key:
        return "—"
    return f"{key[:6]}…{key[-4:]}" if len(key) > 12 else "…" + key[-2:]
