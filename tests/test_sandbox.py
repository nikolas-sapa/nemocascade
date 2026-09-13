import os

import pytest

from nemocascade.sandbox import (
    ExecutionResult,
    LocalSandbox,
    NebiusSandbox,
    SandboxError,
    make_sandbox,
)


def test_local_runs_files_and_captures_output():
    sandbox = LocalSandbox()
    result = sandbox.run(
        command=["python3", "check.py"],
        files={"check.py": "print('OK')\n"},
    )
    assert result.backend == "local"
    assert result.exit_code == 0
    assert result.stdout == "OK\n"
    assert result.timed_out is False


def test_local_captures_failure_exit_code():
    sandbox = LocalSandbox()
    result = sandbox.run(
        command=["python3", "check.py"],
        files={"check.py": "print('FAILED')\nraise SystemExit(3)\n"},
    )
    assert result.exit_code == 3
    assert "FAILED" in result.stdout


def test_local_writes_nested_files(tmp_path):
    sandbox = LocalSandbox()
    result = sandbox.run(
        command=["python3", "-c", "open('out/x.txt').read()"],
        files={"out/x.txt": "nested content\n"},
    )
    assert result.exit_code == 0


def test_local_sandbox_rejects_path_traversal():
    sandbox = LocalSandbox()
    with pytest.raises(SandboxError, match="escapes"):
        sandbox.run(
            command=["python3", "-c", "pass"],
            files={"../escaped.txt": "should not be written\n"},
        )


def test_local_sandbox_scrubs_host_env(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "secret-value")
    sandbox = LocalSandbox()
    result = sandbox.run(
        command=["python3", "-c",
                 "import os; print(os.environ.get('NEBIUS_API_KEY', 'SCRUBBED'))"],
    )
    assert result.stdout.strip() == "SCRUBBED"


def test_local_timeout():
    sandbox = LocalSandbox()
    result = sandbox.run(command=["sleep", "5"], timeout=1)
    assert result.timed_out is True
    assert result.exit_code == -1


def test_nebius_sandbox_contract(mock_base_url):
    base, state = mock_base_url
    sandbox = NebiusSandbox(
        base_url=base, iam_token="iam-token", project="proj-1", timeout=30,
        poll_interval=0.01,
    )
    result = sandbox.run(
        command=["python3", "check.py"],
        files={"check.py": "print('OK')\n"},
        image="tag:python:3.12-slim",
    )
    assert result.backend == "nebius"
    assert result.exit_code == 0
    assert result.stdout == "OK\n"
    assert result.cost == pytest.approx(0.0021)

    # upload -> spawn -> poll flow against the real async contract
    assert state.file_uploads == ["print('OK')\n"]
    spawn = state.spawn_calls[0]
    assert spawn["command"] == "python3"          # string command, per API
    assert spawn["args"] == ["check.py"]          # argv goes in args
    assert spawn["shell"] is False
    assert spawn["disposable"] is True
    assert spawn["cwd"] == "/work"
    assert spawn["image"] == "tag:python:3.12-slim"
    (dest, ref), = spawn["files"].items()
    assert dest == "/work/check.py"
    assert isinstance(ref["uuid"], str) and len(ref["uuid"]) >= 32


def test_nebius_sandbox_polls_until_ready(mock_base_url):
    base, state = mock_base_url
    sandbox = NebiusSandbox(
        base_url=base, iam_token="t", project="p", timeout=30, poll_interval=0.01
    )
    result = sandbox.run(command=["python3", "-c", "print('hi')"])
    assert result.exit_code == 0
    assert "hi" in result.stdout
    # the mock returns 425 on the first poll, so at least 2 polls happened
    op = next(iter(state.operations.values()))
    assert op["polls"] >= 2


def test_nebius_sandbox_requires_project(mock_base_url):
    base, _state = mock_base_url
    sandbox = NebiusSandbox(base_url=base, iam_token="iam-token", project="")
    with pytest.raises(SandboxError):
        sandbox.run(command=["true"])


def test_nebius_sandbox_reports_failure_exit(mock_base_url):
    base, _state = mock_base_url
    sandbox = NebiusSandbox(base_url=base, iam_token="t", project="p",
                            poll_interval=0.01)
    result = sandbox.run(
        command=["python3", "check.py"],
        files={"check.py": "raise SystemExit(1)\n"},
    )
    assert result.exit_code == 1


def test_make_sandbox_unknown_backend():
    with pytest.raises(SandboxError):
        make_sandbox("docker")


def test_make_sandbox_local():
    sandbox = make_sandbox("local", timeout=5)
    assert isinstance(sandbox, LocalSandbox)
    assert sandbox.timeout == 5


def test_execution_result_shape():
    result = ExecutionResult("out", "err", 0, False, None, "local")
    assert result.stdout == "out"
    assert result.cost is None
