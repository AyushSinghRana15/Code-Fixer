"""Full pipeline on the planted-bug cart repo, with a scripted model instead of a real LLM.

Uses the local sandbox (needs `uv` or Python with pip to install pytest into the workspace)."""

from pathlib import Path

import pytest

from fixer.config import Budget
from fixer.events import EventBus
from fixer.llm.router import LLMRouter
from fixer.orchestrator.pipeline import Job, JobConfig
from tests.fakes import ScriptedProvider, call, text

CART = Path(__file__).resolve().parents[1] / "evals" / "bugs" / "py_cart"
REPRO = "tests/test_issue_coupon.py::test_fifteen_percent_coupon"
REPRO_TEST = (
    "from cart.pricing import apply_discount\n\n\ndef test_fifteen_percent_coupon():\n"
    "    assert apply_discount(200, 15) == 170.0\n"
)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXER_HOME", str(tmp_path / "home"))


def run_job(script, **cfg):
    provider = ScriptedProvider(script)
    events = []
    bus = EventBus(events.append)
    router = LLMRouter([provider], max_requests=40, on_event=lambda type, **d: bus.emit(type, **d))
    cfg.setdefault("scouts", "never")  # these tests script a single agent; see test_orchestration.py
    job = Job(
        JobConfig(repo=CART, issue=(CART / "ISSUE.md").read_text(), budget=Budget(max_requests=40), **cfg), router, bus
    )
    return job.run(), events, provider


def test_reproduce_fix_verify_review_deliver():
    original = (CART / "cart" / "pricing.py").read_text()
    script = [
        # reproduce
        call("create_file", path="tests/test_issue_coupon.py", content=REPRO_TEST),
        call("run_tests", selector=REPRO),
        call("finish", test_id=REPRO, explanation="15% off 200 should be 170"),
        # fix
        call("read_file", path="cart/pricing.py"),
        call("edit_file", path="cart/pricing.py", old_text="percent / 10)", new_text="percent / 100)"),
        call("run_tests", selector=REPRO),
        call("finish", summary="apply_discount divided by 10 instead of 100"),
        # review
        text('{"approve": true, "concerns": []}'),
    ]
    result, events, provider = run_job(script)

    assert result.status == "fixed", result.reason
    assert result.repro_test == REPRO
    assert "-    return round(total * (1 - percent / 10), 2)" in result.diff
    assert "+    return round(total * (1 - percent / 100), 2)" in result.diff
    assert result.tests["final"]["new_failures"] == []
    assert result.requests == len(provider.calls) == 8
    assert all(state == "done" for state in result.phases.values())
    assert (CART / "cart" / "pricing.py").read_text() == original  # the user's repo is untouched
    assert Path(result.patch_path).read_text() == result.diff


def test_rejects_a_reproduction_test_that_passes():
    passing = "from cart.pricing import apply_discount\n\n\ndef test_zero():\n    assert apply_discount(80, 0) == 80\n"
    script = [
        call("create_file", path="tests/test_issue_coupon.py", content=passing),
        call("finish", test_id="tests/test_issue_coupon.py::test_zero", explanation="?"),
        call("give_up", reason="can't reproduce"),
    ]
    result, events, _ = run_job(script)
    assert result.status == "gave_up"
    assert any(e.type == "agent.finish_rejected" and "PASSES" in e.data["reason"] for e in events)


def test_fix_phase_cannot_edit_tests():
    script = [
        call("create_file", path="tests/test_issue_coupon.py", content=REPRO_TEST),
        call("finish", test_id=REPRO, explanation="x"),
        call("edit_file", path="tests/test_issue_coupon.py", old_text="170.0", new_text="-100.0"),
        call("give_up", reason="tests are read-only"),
    ]
    result, events, _ = run_job(script)
    assert result.status == "gave_up"
    assert any(e.type == "tool.result" and "read-only" in e.data["preview"] for e in events)
