"""Settings and paths. Secrets come only from environment variables (or a git-ignored .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent


def load_env() -> None:
    """Load backend/.env, then ./.env. Real environment variables always win."""
    load_dotenv(BACKEND_DIR / ".env", override=False)
    load_dotenv(override=False)


def fixer_home() -> Path:
    home = Path(os.environ.get("FIXER_HOME", Path.home() / ".fixer"))
    home.mkdir(parents=True, exist_ok=True)
    return home


@dataclass
class Budget:
    """Hard limits for one job. Requests are the scarce resource on free tiers."""

    max_requests: int = 60
    max_seconds: int = 20 * 60
    scout_iterations: int = 6
    reproduce_iterations: int = 14
    fix_iterations: int = 24
    stuck_repeats: int = 4  # same failing-test signature this many times in a row = stuck
    verify_rounds: int = 2  # times Verify may send the agent back to Fix
    review_rounds: int = 1  # times Review may send the agent back to Fix


def env_flag(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}
