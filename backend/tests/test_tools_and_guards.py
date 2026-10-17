from pathlib import Path

import pytest

from fixer.agent.loop import parse_text_tool_calls
from fixer.guards.tamper import check_diff
from fixer.sandbox.detect import detect
from fixer.sandbox.local import LocalSandbox, safe_env
from fixer.sandbox.results import parse_junit
from fixer.sandbox.workspace import PathError, Workspace
from fixer.tools.toolbox import Policy, Toolbox, ToolError, parse_args

CART = Path(__file__).resolve().parents[1] / "evals" / "bugs" / "py_cart"


@pytest.fixture
def ws(tmp_path):
    return Workspace.create(CART, tmp_path / "repo")


def toolbox(ws, deny_tests=False):
    spec = detect(ws.root)

    def can_write(rel, exists):
        return "tests are read-only" if deny_tests and spec.is_test_path(rel) else None

    return Toolbox(ws, LocalSandbox(ws, spec), Policy("t", can_write))


def test_workspace_is_a_copy_and_paths_are_guarded(ws):
    assert ws.diff() == ""
    for bad in ("../outside.txt", "/etc/passwd", ".git/config"):
        with pytest.raises(PathError):
            ws.resolve(bad)
    assert ws.resolve("cart/pricing.py").is_file()


def test_edit_requires_unique_exact_match(ws):
    tb = toolbox(ws)
    with pytest.raises(ToolError, match="not found"):
        tb.execute("edit_file", {"path": "cart/pricing.py", "old_text": "nope", "new_text": "x"})
    with pytest.raises(ToolError, match="appears"):
        tb.execute("edit_file", {"path": "cart/pricing.py", "old_text": "return round(", "new_text": "x"})
    tb.execute("edit_file", {"path": "cart/pricing.py", "old_text": "percent / 10)", "new_text": "percent / 100)"})
    assert "percent / 100)" in ws.diff()


def test_policy_blocks_writing_tests_while_fixing(ws):
    tb = toolbox(ws, deny_tests=True)
    with pytest.raises(ToolError, match="read-only"):
        tb.execute("edit_file", {"path": "tests/test_pricing.py", "old_text": "25.5", "new_text": "0"})


def test_read_and_search(ws):
    tb = toolbox(ws)
    assert "def apply_discount" in tb.execute("read_file", {"path": "cart/pricing.py"})
    assert "cart/pricing.py:" in tb.execute("search", {"pattern": "def apply_discount"})


def test_tamper_guard_flags_weakened_tests(ws):
    spec = detect(ws.root)
    p = ws.resolve("tests/test_pricing.py")
    p.write_text(
        p.read_text().replace("    assert subtotal([(10.0, 2), (5.5, 1)]) == 25.5\n", "    pass\n")
        + "\n@pytest.mark.skip\ndef test_x():\n    pass\n"
    )
    issues = check_diff(ws.diff(), spec, ws.baseline_files(), ws.changed_files())
    assert any("removed an assertion" in i for i in issues)
    assert any("skipped" in i for i in issues)


def test_tamper_guard_allows_new_tests(ws):
    spec = detect(ws.root)
    ws.resolve("tests/test_new.py").write_text("def test_new():\n    assert 1 + 1 == 2\n")
    assert check_diff(ws.diff(), spec, ws.baseline_files(), ws.changed_files()) == []


def test_junit_parsing_builds_runnable_pytest_ids(tmp_path):
    xml = tmp_path / "junit.xml"
    xml.write_text("""<testsuites><testsuite>
      <testcase classname="tests.test_a" name="test_ok" file="tests/test_a.py"/>
      <testcase classname="tests.test_a.TestCart" name="test_bad" file="tests/test_a.py">
        <failure message="assert 1 == 2">trace</failure></testcase>
      <testcase classname="tests.test_a" name="test_skip" file="tests/test_a.py"><skipped/></testcase>
    </testsuite></testsuites>""")
    r = parse_junit([xml], 1, "")
    assert (r.passed, r.failed, r.skipped) == (1, 1, 1)
    assert r.failures[0].id == "tests/test_a.py::TestCart::test_bad"
    assert not r.ok


def test_sandbox_env_never_contains_secrets(monkeypatch):
    monkeypatch.setenv("FIXER_OPENROUTER_API_KEY", "sk-or-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    env = safe_env()
    assert "FIXER_OPENROUTER_API_KEY" not in env and "GITHUB_TOKEN" not in env


def test_text_tool_calls_are_parsed():
    content = 'Sure.\n<tool_call>{"name": "read_file", "arguments": {"path": "a.py"}}</tool_call>'
    calls = parse_text_tool_calls(content, {"read_file"})
    assert calls and calls[0].name == "read_file" and parse_args(calls[0].arguments) == {"path": "a.py"}
    assert parse_text_tool_calls('```json\n{"tool": "nope", "args": {}}\n```', {"read_file"}) == []


def test_parse_args_tolerates_trailing_commas():
    assert parse_args('{"a": 1,}') == {"a": 1}


# ---- forgiving edits (regressions from the first real run) ----
from fixer.tools.toolbox import replace_once  # noqa: E402

FILE = "def test_add_tax():\n    assert add_tax(100.0, 0.08) == 108.0\n"


def test_edit_matches_despite_wrong_indentation():
    # nemotron copied 6-space indentation from read_file's "    5  " prefix; the file uses 4
    old = "def test_add_tax():\n      assert add_tax(100.0, 0.08) == 108.0"
    new = old + "\n\n\ndef test_coupon():\n      assert apply_discount(200, 15) == 170.0"
    out, how = replace_once(FILE, old, new)
    assert how == "fuzzy" and "def test_coupon" in out
    compile(out, "t.py", "exec")  # still valid Python


def test_edit_strips_copied_line_numbers():
    old = "1\tdef test_add_tax():\n2\t    assert add_tax(100.0, 0.08) == 108.0"
    out, _ = replace_once(FILE, old, "1\tdef test_add_tax():\n2\t    assert add_tax(100.0, 0.08) == 108.00")
    assert out == "def test_add_tax():\n    assert add_tax(100.0, 0.08) == 108.00\n"


def test_edit_not_found_shows_closest_text():
    with pytest.raises(ToolError, match="closest text"):
        replace_once(FILE, "assert add_tax(100, 0.08) == 108", "x")


def test_repeated_read_gets_a_nudge(ws):
    tb = toolbox(ws)
    tb.execute("read_file", {"path": "cart/pricing.py"})
    assert "hasn't changed" in tb.execute("read_file", {"path": "cart/pricing.py"})


def test_alias_arguments_are_mapped(ws):
    # gpt-oss on Groq calls search(query=..., max_results=...) out of habit
    tb = toolbox(ws)
    assert "cart/pricing.py:" in tb.execute("search", {"query": "def apply_discount", "max_results": 5})
    with pytest.raises(ToolError, match="needs: pattern"):
        tb.execute("search", {"max_results": 5})


def test_schemas_sent_to_providers_are_loose():
    from fixer.tools.toolbox import TOOL_SPECS

    params = TOOL_SPECS["search"]["function"]["parameters"]
    assert "required" not in params and "additionalProperties" not in params


def test_bare_argument_object_is_matched_to_its_tool():
    # gpt-oss wrote finish's arguments as plain JSON, without a tool name
    params = {"finish": {"test_id", "explanation"}, "run_tests": {"selector"}}
    calls = parse_text_tool_calls('{\n "test_id": "tests/t.py", "explanation": "fails"\n}', set(params), params)
    assert calls and calls[0].name == "finish"
    assert parse_text_tool_calls('{"path": "x"}', set(params), params) == []  # ambiguous/unknown -> nothing
