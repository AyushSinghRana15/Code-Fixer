import pytest

from fixer.llm.router import LLMRouter, NoProviderAvailable, RequestBudgetExceeded
from tests.fakes import ScriptedProvider, err, text


class Clock:
    def __init__(self):
        self.t = 1_000_000.0
        self.slept: list[float] = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def make(*providers, **kw):
    clock = Clock()
    events = []
    router = LLMRouter(
        list(providers), clock=clock.now, sleep=clock.sleep, on_event=lambda type, **d: events.append((type, d)), **kw
    )
    return router, clock, events


def test_fails_over_when_key_is_rejected():
    a = ScriptedProvider([err("auth")], pid="a")
    b = ScriptedProvider([text("hi")], pid="b")
    router, _, events = make(a, b)
    res = router.chat([{"role": "user", "content": "x"}])
    assert res.provider == "b"
    assert router.status["a"].state == "invalid_key"
    assert any(t == "provider.switched" and d["to"] == "b" for t, d in events)


def test_short_rate_limit_is_waited_out_on_same_provider():
    a = ScriptedProvider([err("rate", retry_after=5), text("ok")], pid="a")
    router, clock, _ = make(a)
    assert router.chat([]).provider == "a"
    assert 5 in clock.slept


def test_long_rate_limit_switches_then_recovers():
    a = ScriptedProvider([err("rate", retry_after=120), text("back on a")], pid="a")
    b = ScriptedProvider([text("from b")], pid="b")
    router, clock, _ = make(a, b)
    assert router.chat([]).provider == "b"
    assert router.status["a"].state == "rate_limited"
    clock.t += 121
    assert router.chat([]).provider == "a"


def test_daily_quota_marks_provider_until_midnight():
    a = ScriptedProvider([err("quota")], pid="a")
    b = ScriptedProvider([text("b")], pid="b")
    router, clock, _ = make(a, b)
    router.chat([])
    st = router.status["a"]
    assert st.state == "quota_exhausted" and st.retry_at > clock.t + 60


def test_missing_model_tries_next_model_then_next_provider():
    a = ScriptedProvider([err("model"), err("model")], pid="a")
    b = ScriptedProvider([text("b")], pid="b")
    router, _, _ = make(a, b)
    assert router.chat([]).provider == "b"
    assert [c["model"] for c in a.calls] == ["m1", "m2"]
    assert router.status["a"].state == "no_model"


def test_too_large_skips_provider_for_this_request_only():
    a = ScriptedProvider([err("too_large"), text("small one fits")], pid="a")
    b = ScriptedProvider([text("b took the big one")], pid="b")
    router, _, _ = make(a, b)
    assert router.chat([]).provider == "b"
    assert router.status["a"].state == "active"
    assert router.chat([]).provider == "a"


def test_private_repo_never_uses_providers_that_train_on_data():
    a = ScriptedProvider([text("should not be used")], pid="a", trains=True)
    router, _, _ = make(a, private_repo=True)
    with pytest.raises(NoProviderAvailable):
        router.chat([])
    assert a.calls == []


def test_request_budget_is_enforced():
    a = ScriptedProvider([text("1"), text("2")], pid="a")
    router, _, _ = make(a, max_requests=1)
    router.chat([])
    with pytest.raises(RequestBudgetExceeded):
        router.chat([])


def test_paces_requests_to_stay_under_rpm():
    a = ScriptedProvider([text("1"), text("2")], pid="a", rpm=20)
    router, clock, _ = make(a)
    router.chat([])
    router.chat([])
    assert clock.slept and clock.slept[-1] == pytest.approx(3.0)


# ---- classifying provider errors ----
import httpx2 as httpx  # noqa: E402  (the openai SDK v3 HTTP client)
import openai  # noqa: E402

from fixer.llm.client import classify  # noqa: E402


def _status_error(status, message, headers=None):
    req = httpx.Request("POST", "https://api.example/v1/chat/completions")
    resp = httpx.Response(status, request=req, headers=headers or {})
    cls = openai.RateLimitError if status == 429 else openai.APIStatusError
    return cls(message, response=resp, body=None)


def test_tpm_limit_with_room_left_is_a_short_rate_limit():
    e = classify(
        _status_error(
            429,
            "Rate limit reached on tokens per minute (TPM): Limit 8000, Used 6100, "
            "Requested 2500. Please try again in 4.2s.",
        )
    )
    assert e.kind == "rate" and e.retry_after == pytest.approx(4.2)


def test_single_request_over_tpm_limit_is_too_large():
    e = classify(_status_error(429, "tokens per minute (TPM): Limit 8000, Used 0, Requested 9100."))
    assert e.kind == "too_large"


def test_daily_quota():
    assert classify(_status_error(429, "Rate limit exceeded: free-models-per-day")).kind == "quota"


def test_malformed_tool_call_is_retried_on_same_model():
    a = ScriptedProvider([err("flaky"), text("ok")], pid="a")
    router, _, _ = make(a)
    assert router.chat([]).provider == "a"
    assert [c["model"] for c in a.calls] == ["m1", "m1"]


def test_groq_tool_use_failed_is_flaky():
    e = classify(
        _status_error(
            400,
            "Failed to call a function. Please adjust your prompt. "
            "See 'failed_generation' for more details. code: tool_use_failed",
        )
    )
    assert e.kind == "flaky"


def test_first_429_without_retry_after_retries_same_provider():
    a = ScriptedProvider([err("rate"), text("ok")], pid="a")
    b = ScriptedProvider([text("b")], pid="b")
    router, clock, _ = make(a, b)
    assert router.chat([]).provider == "a"
    assert router.status["a"].state == "active" and 8.0 in clock.slept


def test_unparseable_failed_generation_becomes_text_reply():
    from fixer.llm.client import ProviderError, recover_failed_generation

    e = ProviderError("flaky", "Parsing failed")
    e.body = {"error": {"failed_generation": "I'll call search with pattern apply_discount"}}
    msg = recover_failed_generation(e, {"search"})
    assert msg and msg.content.startswith("I'll call search") and not msg.tool_calls
