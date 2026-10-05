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


@pytest.mark.parametrize("field", ["solution_path", "image"])
@pytest.mark.parametrize("scope", ["suite", "task"])
@pytest.mark.parametrize("value", [None, 42, True, [], {}])
def test_required_string_fields_reject_invalid_json(tmp_path, field, scope, value):
    task = {"id": "a", "prompt": "p", "verify": {"command": ["true"]}}
    suite = {"tasks": [task]}
    target = suite if scope == "suite" else task
    target[field] = value
    path = _write(tmp_path, suite)

    with pytest.raises(TaskFormatError) as raised:
        load_tasks(path)

    message = str(raised.value)
    assert path in message
    assert field in message
    assert ("suite" if scope == "suite" else "task 'a'") in message
    assert "string" in message


@pytest.mark.parametrize("case", ["omitted", "override", "inherit"])
def test_required_string_fields_keep_defaults_and_overrides(tmp_path, case):
    task = {"id": "a", "prompt": "p", "verify": {"command": ["true"]}}
    suite = {"tasks": [task]}
    expected_defaults = {"solution_path": "solution.py", "image": "tag:python:3.12-slim"}
    if case != "omitted":
        expected_defaults = {"solution_path": "suite.py", "image": "suite:image"}
        suite.update(expected_defaults)
    expected_task = expected_defaults
    if case == "override":
        expected_task = {"solution_path": "task.py", "image": "task:image"}
        task.update(expected_task)

    tasks, defaults = load_tasks(_write(tmp_path, suite))

    assert defaults == expected_defaults
    assert len(tasks) == 1
    assert tasks[0].solution_path == expected_task["solution_path"]
    assert tasks[0].image == expected_task["image"]
