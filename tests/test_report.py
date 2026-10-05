import pytest

from nemocascade.cascade import Step, TaskResult
from nemocascade.client import Tier
from nemocascade.report import json_to_markdown, results_to_json

NANO = Tier(tier="nano", model="nvidia/nemotron-3-nano-4b-instruct",
            price_in_per_1m=0.04, price_out_per_1m=0.16)
PASS_COST = (240 * 0.04 + 90 * 0.16) / 1e6


def _fake_results():
    step_pass = Step(tier="nano", model=NANO.model, verdict="pass",
                     tokens_in=240, tokens_out=90, cost=PASS_COST,
                     exit_code=0, stdout_tail="OK")
    step_fail = Step(tier="nano", model=NANO.model, verdict="fail",
                     tokens_in=240, tokens_out=90, cost=PASS_COST,
                     exit_code=1, stderr_tail="FAILED: edge-case")
    step_unpriced = Step(tier="nano", model=NANO.model, verdict="fail",
                         exit_code=1, stderr_tail="boom")
    return [
        TaskResult(task_id="easy", success=True, steps=[step_pass],
                   final_model=NANO.model, total_cost=PASS_COST,
                   sandbox_backend="local"),
        TaskResult(task_id="needs-escalation", success=True,
                   steps=[step_fail, step_pass], final_model=NANO.model,
                   total_cost=PASS_COST * 2, sandbox_backend="local"),
        TaskResult(task_id="hopeless", success=False, steps=[step_unpriced],
                   sandbox_backend="local"),
    ]


def test_results_to_json_summary():
    report = results_to_json(_fake_results())
    s = report["summary"]
    assert s["tasks"] == 3
    assert s["succeeded"] == 2
    assert s["success_rate"] == round(2 / 3, 4)
    assert s["escalated"] == 1
    assert s["first_tier_successes"] == 1
    assert s["priced"] is False  # one task has an unpriced step
    assert s["total_cost"] is None
    assert report["tasks"][0]["steps"][0]["cost"] == pytest.approx(PASS_COST)


def test_results_to_json_tier_buckets():
    report = results_to_json(_fake_results())
    nano = next(t for t in report["tiers"] if t["tier"] == "nano")
    assert nano["calls"] == 4
    assert nano["passes"] == 2
    assert nano["fails"] == 2
    assert nano["tokens_in"] == 240 * 3  # the unpriced step recorded no usage
    assert nano["tokens_out"] == 90 * 3


def test_markdown_report_contents():
    report = results_to_json(_fake_results())
    md = json_to_markdown(report)
    assert "# nemocascade run report" in md
    assert "needs-escalation — PASS" in md
    assert "hopeless — FAIL" in md
    assert "| step | tier | model | verdict |" in md
    assert "FAILED: edge-case" in md
    assert "pricing incomplete" in md


def test_zero_cost_report_is_priced():
    report = results_to_json([TaskResult(task_id="free", success=True, total_cost=0.0)])
    assert report["summary"]["priced"] is True
    assert report["summary"]["total_cost"] == 0.0
    assert "$0.000000" in json_to_markdown(report)


def test_markdown_report_shows_cost_when_priced():
    results = [r for r in _fake_results() if r.task_id != "hopeless"]
    md = json_to_markdown(results_to_json(results))
    assert "$0.000072" in md  # 3 priced nano calls x $0.000024
