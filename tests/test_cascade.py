import pytest

from conftest import TASKS, TASKS_NEGATIVE, TEST_CONFIG
from nemocascade.cascade import Cascade, extract_code_block
from nemocascade.client import TokenFactoryClient, resolve_ladder
from nemocascade.sandbox import LocalSandbox, NebiusSandbox
from nemocascade.tasks import load_tasks


def make_cascade(mock_base_url, sandbox=None):
    base, _state = mock_base_url
    client = TokenFactoryClient(base_url=f"{base}/v1", api_key="test-key")
    ladder = resolve_ladder(client, TEST_CONFIG)
    if sandbox is None:
        sandbox = NebiusSandbox(base_url=base, iam_token="t", project="p", timeout=30)
    return Cascade(client, ladder, sandbox)


def _task(path, task_id):
    tasks, _defaults = load_tasks(str(path))
    return next(t for t in tasks if t.id == task_id)


def test_extract_code_block():
    text = "Sure!\n```python\nprint('hi')\n```\nDone."
    assert extract_code_block(text) == "print('hi')"
    assert extract_code_block("no code here") is None
    assert extract_code_block("```\nbare\n```") == "bare"


def test_first_tier_success(mock_base_url):
    cascade = make_cascade(mock_base_url)
    result = cascade.run_task(_task(TASKS, "total-value"))
    assert result.success is True
    assert len(result.steps) == 1
    assert result.steps[0].verdict == "pass"
    assert result.steps[0].tier == "nano"
    assert result.steps[0].cost == pytest.approx((240 * 0.04 + 90 * 0.16) / 1e6)
    assert result.total_cost == pytest.approx(result.steps[0].cost)


def test_escalates_on_verified_failure(mock_base_url):
    base, state = mock_base_url
    cascade = make_cascade(mock_base_url)
    result = cascade.run_task(_task(TASKS, "normalize-name"))
    assert result.success is True
    assert [s.verdict for s in result.steps] == ["fail", "pass"]
    assert result.steps[0].tier == "nano"
    assert result.steps[0].exit_code == 1
    assert result.steps[1].tier == "super"
    assert result.final_model == "nvidia/nemotron-3-super-49b-instruct"
    second_call = state.chat_calls[1]
    assert second_call["keyword"] == "normalize_name"
    user_msgs = [m for m in second_call["messages"] if m["role"] == "user"]
    assert "already attempted" in user_msgs[0]["content"]
    assert "x] nano" in user_msgs[0]["content"]


def test_full_ladder_escalation(mock_base_url):
    cascade = make_cascade(mock_base_url)
    result = cascade.run_task(_task(TASKS, "balanced-brackets"))
    assert result.success is True
    assert [s.tier for s in result.steps] == ["nano", "super", "ultra"]
    assert [s.verdict for s in result.steps] == ["fail", "fail", "pass"]
    assert result.final_model == "nvidia/nemotron-3-ultra-253b-instruct"
    expected = (
        (240 * 0.04 + 90 * 0.16)
        + (610 * 0.40 + 210 * 1.60)
        + (1180 * 2.00 + 460 * 8.00)
    ) / 1e6
    assert result.total_cost == pytest.approx(expected)


def test_no_artifact_escalates_without_sandbox(mock_base_url):
    _base, state = mock_base_url
    cascade = make_cascade(mock_base_url)
    result = cascade.run_task(_task(TASKS_NEGATIVE, "prose-only"))
    assert result.success is False
    assert all(s.verdict == "no_artifact" for s in result.steps)
    assert len(result.steps) == 3
    assert result.final_model is None
    # no sandbox spawn may happen for responses without an artifact
    spawn_calls_before = len(state.spawn_calls)
    cascade.run_task(_task(TASKS_NEGATIVE, "prose-only"))
    assert len(state.spawn_calls) == spawn_calls_before


def test_null_usage_and_content_do_not_crash(mock_base_url, monkeypatch):
    cascade = make_cascade(mock_base_url)

    # usage: null must not raise, and content: null must count as no_artifact
    def null_payload(model, messages, **kwargs):
        return {"choices": [{"message": {"role": "assistant", "content": None}}],
                "usage": None}

    monkeypatch.setattr(cascade.client, "chat", null_payload)
    result = cascade.run_task(_task(TASKS, "total-value"))
    assert result.success is False
    assert [s.verdict for s in result.steps] == ["no_artifact"] * 3
    assert all(s.tokens_in == 0 and s.tokens_out == 0 for s in result.steps)

    # a fine response with missing usage keys still executes normally
    solution = (
        "def total_value(items_csv):\n"
        "    total = 0.0\n"
        "    for line in items_csv.splitlines():\n"
        "        if not line.strip():\n"
        "            continue\n"
        "        _n, q, p = line.split(',')\n"
        "        total += int(q) * float(p)\n"
        "    return total\n"
    )

    def no_usage(model, messages, **kwargs):
        return {"choices": [{"message": {"role": "assistant", "content":
                f"```python\n{solution}```"}}]}

    monkeypatch.setattr(cascade.client, "chat", no_usage)
    result = cascade.run_task(_task(TASKS, "total-value"))
    assert result.success is True
    assert result.steps[0].tokens_in == 0


def test_all_tiers_fail_reports_cleanly(mock_base_url):
    cascade = make_cascade(mock_base_url)
    result = cascade.run_task(_task(TASKS_NEGATIVE, "impossible"))
    assert result.success is False
    assert [s.verdict for s in result.steps] == ["fail", "fail", "fail"]
    assert all(s.exit_code == 1 for s in result.steps)
    assert "FAILED" in result.steps[0].stdout_tail


def test_api_errors_abort_without_escalation(mock_base_url):
    _base, _state = mock_base_url
    cascade = make_cascade(mock_base_url)
    cascade.client.api_key = ""  # the nano call returns HTTP 401
    result = cascade.run_task(_task(TASKS, "total-value"))
    assert result.success is False
    # infrastructure errors stop the ladder instead of escalating: a 401 on
    # the cheapest tier must not silently bill super/ultra calls
    assert [s.verdict for s in result.steps] == ["error"]
    assert "HTTP 401" in result.steps[0].detail


def test_sandbox_backend_failure_aborts_ladder(mock_base_url, monkeypatch):
    cascade = make_cascade(mock_base_url)

    class Boom:
        backend = "nebius"

        def run(self, **kwargs):
            raise RuntimeError("sandbox exploded")

    monkeypatch.setattr(cascade, "sandbox", Boom())
    result = cascade.run_task(_task(TASKS, "total-value"))
    assert result.success is False
    assert [s.verdict for s in result.steps] == ["error"]
    assert "sandbox exploded" in result.steps[0].detail


def test_local_sandbox_backend_equivalence(mock_base_url):
    cascade = make_cascade(mock_base_url, sandbox=LocalSandbox(timeout=30))
    result = cascade.run_task(_task(TASKS, "normalize-name"))
    assert result.success is True
    assert [s.verdict for s in result.steps] == ["fail", "pass"]
    assert result.sandbox_backend == "local"
