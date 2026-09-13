"""The escalation cascade: cheap tier first, sandbox-verified, escalate on failure.

For every task the cascade walks the ladder from cheapest to most expensive tier:

1. Ask the tier's model for a solution (single fenced code block).
2. Extract the artifact; a response without one counts as a verified failure
   (nothing to execute) and triggers escalation.
3. Execute the artifact against the task's verifier in the sandbox.
4. On a passing run the task is done; otherwise the next tier runs, armed with
   the previous tier's failure evidence in its prompt.

The result is a full trace: which tier solved the task, what the sandbox saw,
and what each attempt cost.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .client import Tier, TokenFactoryClient
from .tasks import Task

CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)

EVIDENCE_TAIL = 400


@dataclass
class Step:
    tier: str
    model: str
    verdict: str  # "pass" | "fail" | "no_artifact" | "error"
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float | None = None
    exit_code: int | None = None
    timed_out: bool = False
    stdout_tail: str = ""
    stderr_tail: str = ""
    detail: str = ""
    elapsed_s: float = 0.0


@dataclass
class TaskResult:
    task_id: str
    success: bool
    steps: list[Step] = field(default_factory=list)
    final_model: str | None = None
    total_cost: float | None = None
    sandbox_backend: str = ""

    def evidence(self) -> str:
        """One-line-per-step evidence summary used in reports and escalation."""
        lines = []
        for step in self.steps:
            marker = {"pass": "+", "fail": "x", "no_artifact": "!", "error": "e"}[step.verdict]
            line = f"[{marker}] {step.tier} ({step.model})"
            if step.verdict == "fail":
                line += f" exit={step.exit_code}"
            elif step.verdict == "error":
                line += f" {step.detail[:120]}"
            lines.append(line)
        return "\n".join(lines)


def extract_code_block(text: str) -> str | None:
    """Return the first fenced code block body, or None when there is none."""
    match = CODE_BLOCK_RE.search(text)
    return match.group(1).strip() if match else None


def _tail(text: str, limit: int = EVIDENCE_TAIL) -> str:
    text = text or ""
    return text[-limit:]


def build_messages(task: Task, prior: TaskResult | None, tier: Tier) -> list[dict]:
    system = (
        "You are a careful software engineer. Respond with exactly one fenced "
        f"python code block containing the complete content of {task.solution_path}. "
        "No prose before or after the code block. The code must satisfy the checks "
        "it will be executed against, using only the Python standard library."
    )
    user = task.prompt
    if prior and prior.steps:
        user += (
            "\n\nA cheaper model already attempted this task and failed execution "
            "verification. Here is what happened:\n"
            f"{prior.evidence()}\n"
            f"Last stderr observed:\n{_tail(prior.steps[-1].stderr_tail, 300)}\n"
            "Fix the problem and return the complete corrected file."
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


class Cascade:
    def __init__(
        self,
        client: TokenFactoryClient,
        ladder: list[Tier],
        sandbox,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ):
        self.client = client
        self.ladder = ladder
        self.sandbox = sandbox
        self.temperature = temperature
        self.max_tokens = max_tokens

    def run_task(self, task: Task) -> TaskResult:
        result = TaskResult(
            task_id=task.id, success=False, sandbox_backend=getattr(self.sandbox, "backend", "?")
        )
        costs: list[float] = []
        prior: TaskResult | None = None

        for index, tier in enumerate(self.ladder):
            started = time.monotonic()
            step = Step(tier=tier.tier, model=tier.model, verdict="error")

            # Inference + artifact extraction. Any failure here (API error,
            # malformed response, unexpected shape) aborts the ladder: it is
            # an infrastructure/protocol problem, not a verified quality
            # failure, and escalating it would misreport the cascade.
            try:
                response = self.client.chat(
                    tier.model,
                    build_messages(task, prior, tier),
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                usage = response.get("usage") or {}
                step.tokens_in = int(usage.get("prompt_tokens") or 0)
                step.tokens_out = int(usage.get("completion_tokens") or 0)
                step.cost = tier.cost(step.tokens_in, step.tokens_out)
                if step.cost is not None:
                    costs.append(step.cost)
                choices = response.get("choices") or []
                message = {}
                if choices and isinstance(choices[0], dict):
                    message = choices[0].get("message") or {}
                artifact = extract_code_block(message.get("content") or "")
            except Exception as exc:  # noqa: BLE001 — one bad tier must not kill the suite
                step.detail = f"{type(exc).__name__}: {exc}"
                step.elapsed_s = time.monotonic() - started
                result.steps.append(step)
                break

            if artifact is None:
                step.verdict = "no_artifact"
                step.detail = "response contained no fenced code block"
                step.elapsed_s = time.monotonic() - started
                result.steps.append(step)
                prior = self._prior_with(step)
                continue

            files = dict(task.verify.get("files", {}))
            files[task.solution_path] = artifact
            try:
                execution = self.sandbox.run(
                    command=task.verify["command"],
                    files=files,
                    image=task.image,
                    timeout=task.verify.get("timeout"),
                )
            except Exception as exc:  # noqa: BLE001 — sandbox backend failure aborts too
                step.verdict = "error"
                step.detail = f"{type(exc).__name__}: {exc}"
                step.elapsed_s = time.monotonic() - started
                result.steps.append(step)
                break

            step.exit_code = execution.exit_code
            step.timed_out = execution.timed_out
            step.stdout_tail = _tail(execution.stdout)
            step.stderr_tail = _tail(execution.stderr)
            pattern = task.verify.get("stdout_regex")
            pattern_ok = True if not pattern else re.search(pattern, execution.stdout) is not None
            expected_exit = task.verify.get("expect_exit", 0)
            passed = (
                not execution.timed_out
                and execution.exit_code == expected_exit
                and pattern_ok
            )
            step.verdict = "pass" if passed else "fail"
            step.elapsed_s = time.monotonic() - started
            result.steps.append(step)

            if passed:
                result.success = True
                result.final_model = tier.model
                break
            prior = self._prior_with(step)

        result.total_cost = sum(costs) if costs else None
        return result

    @staticmethod
    def _prior_with(step: Step) -> TaskResult:
        """A lightweight prior-result view used to brief the next tier."""
        return TaskResult(task_id="", success=False, steps=[step])


def run_suite(cascade: Cascade, tasks: list[Task], only: list[str] | None = None) -> list[TaskResult]:
    selected = [t for t in tasks if not only or t.id in only]
    return [cascade.run_task(task) for task in selected]
