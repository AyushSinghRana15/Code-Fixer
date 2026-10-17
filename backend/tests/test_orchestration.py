"""Orchestrated run: 2 parallel scouts → reproducer with briefs → 2 parallel fixers racing in separate sandboxes."""

from pathlib import Path

import pytest

from fixer.config import Budget
from fixer.events import EventBus
from fixer.llm.router import LLMRouter
from fixer.orchestrator.pipeline import Job, JobConfig
from tests.fakes import AgentBrain, call, text

CART = Path(__file__).resolve().parents[1] / "evals" / "bugs" / "py_cart"
REPRO = "tests/test_issue_coupon.py::test_fifteen_percent_coupon"
REPRO_TEST = (
    "from cart.pricing import apply_discount\n\n\ndef test_fifteen_percent_coupon():\n"
    "    assert apply_discount(200, 15) == 170.0\n"
)

SCRIPTS = {
    "scout-tests": [
        call("list_dir", path="tests"),
        call(
            "finish",
            brief="Tests live in tests/, plain pytest functions; they import from cart.pricing "
            "directly, e.g. `from cart.pricing import apply_discount`. No fixtures.",
        ),
    ],
    "scout-code": [
        call("search", pattern="def apply_discount"),
        call(
            "finish",
            brief="cart/pricing.py:9 apply_discount: `return round(total * (1 - percent / 10), 2)`. "
            "Root cause: divides percent by 10 instead of 100.",
        ),
    ],
    # with the briefs, the reproducer writes the test straight away (no exploration turns)
    "reproducer": [
        call("create_file", path="tests/test_issue_coupon.py", content=REPRO_TEST),
        call("finish", test_id=REPRO, explanation="15% off 200 should be 170"),
    ],
    "fixer": [
        call("edit_file", path="cart/pricing.py", old_text="percent / 10)", new_text="percent / 100)"),
        call("finish", summary="apply_discount divided by 10 instead of 100"),
    ],
    "critic": [text('{"approve": true, "concerns": []}')],
}


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXER_HOME", str(tmp_path / "home"))


def test_scouts_and_parallel_fixers():
    brain = AgentBrain(SCRIPTS)
    events = []
    bus = EventBus(events.append)
    router = LLMRouter(
        [brain.provider("p1"), brain.provider("p2")], max_requests=40, on_event=lambda type, **d: bus.emit(type, **d)
    )
    cfg = JobConfig(
        repo=CART,
        issue=(CART / "ISSUE.md").read_text(),
        budget=Budget(max_requests=40),
        scouts="always",
        candidates=2,
        stagger=0,
    )
    result = Job(cfg, router, bus).run()

    assert result.status == "fixed", result.reason
    assert result.winner in ("fixer-a", "fixer-b")
    assert sorted(result.candidates) == ["fixer-a", "fixer-b"]
    assert result.candidates[result.winner] == "won"
    assert "+    return round(total * (1 - percent / 100), 2)" in result.diff
    assert "tests/test_issue_coupon.py" in result.diff  # repro test + winning fix in one patch
    # every agent was accounted separately
    assert {"scout-tests", "scout-code", "reproducer", "critic"} <= set(result.agents)
    assert any(a.startswith("fixer-") for a in result.agents)
    # the reproducer got the briefs, so it needed no exploration turns
    assert result.agents["reproducer"]["requests"] == 2
    # the two fixers started on different providers (spreads free-tier rate limits)
    first = {c.split(":")[0] for c in brain.calls if c.endswith("fixer:0")}
    assert first == {"p1", "p2"}


def test_auto_mode_skips_scouts_and_staggered_backup_is_not_needed():
    """Default settings: the code-built pack finds apply_discount, so no LLM scouts run; fixer-a wins within
    the stagger window, so the backup fixer never starts. Fewest requests for an easy bug."""
    brain = AgentBrain(SCRIPTS)
    bus = EventBus()
    router = LLMRouter(
        [brain.provider("p1"), brain.provider("p2")], max_requests=40, on_event=lambda type, **d: bus.emit(type, **d)
    )
    cfg = JobConfig(
        repo=CART,
        issue=(CART / "ISSUE.md").read_text(),
        budget=Budget(max_requests=40),
        scouts="auto",
        candidates=2,
        stagger=5,
    )
    result = Job(cfg, router, bus).run()

    assert result.status == "fixed", result.reason
    assert not any(a.startswith("scout") for a in result.agents)
    assert result.candidates == {"fixer-a": "won", "fixer-b": "not needed (fixer-a won before the backup started)"}
    assert result.requests == 2 + 2 + 1  # reproducer + fixer-a + critic
