import json

import pytest

from nemocascade.tasks import TaskFormatError, load_tasks


def _write(tmp_path, suite):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(suite), encoding="utf-8")
    return str(path)


def test_valid_suite_loads(tmp_path):
    path = _write(tmp_path, {
        "solution_path": "sol.py",
        "image": "tag:python:3.12-slim",
        "tasks": [{"id": "a", "prompt": "do it",
                   "verify": {"command": ["python3", "check.py"],
                              "stdout_regex": "^OK$"}}],
    })
    tasks, defaults = load_tasks(path)
    assert len(tasks) == 1
    assert tasks[0].solution_path == "sol.py"
    assert tasks[0].image == "tag:python:3.12-slim"
    assert defaults["solution_path"] == "sol.py"


def test_invalid_stdout_regex_is_a_format_error(tmp_path):
    path = _write(tmp_path, {
        "tasks": [{"id": "a", "prompt": "p",
                   "verify": {"command": ["true"], "stdout_regex": "(unclosed"}}]
    })
    with pytest.raises(TaskFormatError, match="stdout_regex"):
        load_tasks(path)


def test_duplicate_ids_rejected(tmp_path):
    task = {"id": "a", "prompt": "p", "verify": {"command": ["true"]}}
    path = _write(tmp_path, {"tasks": [task, task]})
    with pytest.raises(TaskFormatError, match="duplicate"):
        load_tasks(path)


def test_missing_command_rejected(tmp_path):
    path = _write(tmp_path, {"tasks": [{"id": "a", "prompt": "p", "verify": {}}]})
    with pytest.raises(TaskFormatError, match="verify.command"):
        load_tasks(path)


def test_missing_prompt_rejected(tmp_path):
    path = _write(tmp_path, {"tasks": [{"id": "a", "verify": {"command": ["true"]}}]})
    with pytest.raises(TaskFormatError, match="prompt"):
        load_tasks(path)
