"""Cost/quality report rendering (JSON + Markdown) from TaskResult traces."""

from __future__ import annotations

import json
from dataclasses import asdict

from .cascade import TaskResult


def results_to_json(results: list[TaskResult]) -> dict:
    succeeded = [r for r in results if r.success]
    costs = [r.total_cost for r in results if r.total_cost is not None]
    priced = bool(results) and all(r.total_cost is not None for r in results)
    per_tier: dict[str, dict] = {}
    for result in results:
        for step in result.steps:
            bucket = per_tier.setdefault(
                step.tier, {"tier": step.tier, "model": step.model, "calls": 0,
                            "tokens_in": 0, "tokens_out": 0, "passes": 0, "fails": 0,
                            "no_artifacts": 0, "errors": 0}
            )
            bucket["calls"] += 1
            bucket["tokens_in"] += step.tokens_in
            bucket["tokens_out"] += step.tokens_out
            if step.verdict == "pass":
                bucket["passes"] += 1
            elif step.verdict == "fail":
                bucket["fails"] += 1
            elif step.verdict == "no_artifact":
                bucket["no_artifacts"] += 1
            else:
                bucket["errors"] += 1
    return {
        "summary": {
            "tasks": len(results),
            "succeeded": len(succeeded),
            "success_rate": round(len(succeeded) / len(results), 4) if results else 0.0,
            "escalated": sum(1 for r in results if r.success and len(r.steps) > 1),
            "first_tier_successes": sum(1 for r in results if r.success and len(r.steps) == 1),
            "total_cost": round(sum(costs), 6) if priced else None,
            "priced": priced,
        },
        "tiers": sorted(per_tier.values(), key=lambda t: t["tier"]),
        "tasks": [asdict(r) for r in results],
    }


def _md_cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("`", "'").replace("\n", " ")


def json_to_markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        "# nemocascade run report",
        "",
        (
            f"**Tasks:** {s['tasks']}  ·  **Succeeded:** {s['succeeded']} "
            f"({s['success_rate']:.0%})  ·  **Solved at first (cheapest) tier:** {s['first_tier_successes']}  ·  "
            f"**Escalated:** {s['escalated']}"
        ),
    ]
    if s.get("priced") and s.get("total_cost") is not None:
        lines.append(f"**Estimated cost:** ${s['total_cost']:.6f} (configured prices)")
    else:
        lines.append(
            "**Estimated cost:** unavailable (pricing incomplete); known step costs and token counts retained."
        )

    lines += ["", "## Tier usage", "",
              "| tier | model | calls | tokens in | tokens out | pass | fail | no artifact | error |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for t in report["tiers"]:
        lines.append(
            f"| {t['tier']} | `{_md_cell(t['model'])}` | {t['calls']} | "
            f"{t['tokens_in']} | {t['tokens_out']} | {t['passes']} | {t['fails']} | "
            f"{t.get('no_artifacts', 0)} | {t['errors']} |"
        )

    lines += ["", "## Task results", ""]
    for task in report["tasks"]:
        verdict = "PASS" if task["success"] else "FAIL"
        final = task.get("final_model") or "-"
        lines.append(f"### {task['task_id']} — {verdict} (solved by `{_md_cell(final)}`)")
        lines.append("")
        lines.append("| step | tier | model | verdict | tokens in/out | exit | evidence |")
        lines.append("|---|---|---|---|---|---|---|")
        for i, step in enumerate(task["steps"], 1):
            tokens = f"{step['tokens_in']}/{step['tokens_out']}"
            evidence = step.get("stderr_tail") or step.get("stdout_tail") or step.get("detail") or ""
            lines.append(
                f"| {i} | {step['tier']} | `{_md_cell(step['model'])}` | "
                f"{step['verdict']} | {tokens} | {step.get('exit_code', '-')} | "
                f"`{_md_cell(evidence[-160:])}` |"
            )
        lines.append("")
    return "\n".join(lines)


def write_report(report: dict, json_path: str, md_path: str | None = None) -> None:
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    if md_path:
        with open(md_path, "w", encoding="utf-8") as handle:
            handle.write(json_to_markdown(report))
