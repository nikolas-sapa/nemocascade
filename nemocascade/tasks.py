"""Task definitions and loading.

A task file is JSON (kept dependency-free, no YAML):

{
  "solution_path": "solution.py",
  "image": "tag:python:3.12-slim",
  "tasks": [
    {
      "id": "example",
      "prompt": "Write solution.py implementing ...",
      "verify": {
        "command": ["python3", "check.py"],
        "files": {"check.py": "..."},
        "expect_exit": 0,
        "stdout_regex": "^OK$",
        "timeout": 30
      }
    }
  ]
}
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


class TaskFormatError(ValueError):
    pass


@dataclass
class Task:
    id: str
    prompt: str
    solution_path: str
    image: str
    verify: dict = field(default_factory=dict)


def load_tasks(path: str) -> tuple[list[Task], dict]:
    """Load a task suite. Returns (tasks, defaults) where defaults carries
    suite-level fields (solution_path, image) already applied to each task."""
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    if not isinstance(raw, dict) or not isinstance(raw.get("tasks"), list):
        raise TaskFormatError(f"{path}: expected a JSON object with a 'tasks' list")

    default_solution = raw.get("solution_path", "solution.py")
    default_image = raw.get("image", "tag:python:3.12-slim")

    tasks: list[Task] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw["tasks"]):
        if not isinstance(entry, dict):
            raise TaskFormatError(f"{path}: task #{index} is not an object")
        task_id = entry.get("id")
        if not task_id:
            raise TaskFormatError(f"{path}: task #{index} is missing 'id'")
        if task_id in seen:
            raise TaskFormatError(f"{path}: duplicate task id '{task_id}'")
        seen.add(task_id)
        if not entry.get("prompt"):
            raise TaskFormatError(f"{path}: task '{task_id}' is missing 'prompt'")
        verify = entry.get("verify") or {}
        if not verify.get("command"):
            raise TaskFormatError(f"{path}: task '{task_id}' has no verify.command")
        pattern = verify.get("stdout_regex")
        if pattern:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise TaskFormatError(
                    f"{path}: task '{task_id}' has invalid stdout_regex: {exc}"
                ) from exc
        tasks.append(
            Task(
                id=task_id,
                prompt=entry["prompt"],
                solution_path=entry.get("solution_path", default_solution),
                image=entry.get("image", default_image),
                verify=verify,
            )
        )
    return tasks, {"solution_path": default_solution, "image": default_image}
