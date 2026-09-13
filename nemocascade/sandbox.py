"""Sandbox execution backends.

Two interchangeable backends implement the same contract:

* ``LocalSandbox``   — runs the command as a subprocess in a throwaway temp dir.
                       Zero setup, used for tests, CI, and offline demos.
                       NOT a security boundary: it runs on the host with a
                       scrubbed environment (no secrets), but with host compute.
* ``NebiusSandbox``  — drives the Token Factory Sandboxes (ConTree) REST API:
                       upload files -> spawn a disposable instance -> poll the
                       operation until the subprocess result is ready.

Both return an ``ExecutionResult`` with stdout / stderr / exit_code /
timed_out / resources cost.

Honest status: the Nebius backend is implemented from the published Sandboxes
API reference (as of 2026-09-13) and is contract-tested against the in-repo
mock only. Run the live smoke test in SUBMISSION_CHECKLIST.md before trusting
live results.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_SANDBOXES_BASE_URL = "https://api.tokenfactory.nebius.com/sandboxes"

DEFAULT_INSTANCE_CWD = "/work"


class SandboxError(RuntimeError):
    """Raised when the sandbox backend itself fails (not the verified command)."""


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    cost: float | None
    backend: str


def _safe_write(root: str, rel_path: str, content: str) -> str:
    """Write content under root, refusing paths that escape the sandbox root."""
    root_real = os.path.realpath(root)
    dest = os.path.realpath(os.path.join(root, rel_path))
    if dest != root_real and not dest.startswith(root_real + os.sep):
        raise SandboxError(f"task file path escapes the sandbox root: {rel_path!r}")
    os.makedirs(os.path.dirname(dest) or root_real, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as handle:
        handle.write(content)
    return dest


def _scrubbed_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Minimal environment for subprocess backends — no secrets, no host noise."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONIOENCODING": "utf-8",
        "LANG": "C.UTF-8",
    }
    env.update(extra or {})
    return env


class LocalSandbox:
    """Subprocess sandbox mirroring the Sandboxes request/response contract."""

    backend = "local"

    def __init__(self, timeout: float = 60.0):
        self.timeout = timeout

    def run(
        self,
        command: list[str],
        files: dict[str, str] | None = None,
        image: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> ExecutionResult:
        del image  # accepted for contract parity; local runs use the host interpreter
        effective_timeout = timeout or self.timeout
        with tempfile.TemporaryDirectory(prefix="nemocascade-sandbox-") as tmp:
            for rel_path, content in (files or {}).items():
                _safe_write(tmp, rel_path, content)
            try:
                proc = subprocess.run(
                    command,
                    cwd=tmp,
                    capture_output=True,
                    text=True,
                    timeout=effective_timeout,
                    env=_scrubbed_env(env),
                )
            except subprocess.TimeoutExpired as exc:
                return ExecutionResult(
                    stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
                    stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
                    exit_code=-1,
                    timed_out=True,
                    cost=None,
                    backend=self.backend,
                )
            return ExecutionResult(
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
                timed_out=False,
                cost=None,
                backend=self.backend,
            )


class NebiusSandbox:
    """Token Factory Sandboxes (ConTree) REST backend.

    Flow per the API reference:
      1. ``POST /v1/files``            — upload each file, get its uuid
      2. ``POST /v1/instances``        — spawn a disposable instance; the async
         operation id arrives in the ``Location`` header (``/v1/operations/<id>``)
      3. ``GET /v1/operations/<id>/subprocesses/1`` — poll the main subprocess
         result; 425 + ``Retry-After`` until events exist, ``exit_code == -1``
         while still running.

    Notes on the real contract:
      * ``command`` is a string (the executable); extra argv goes in ``args``.
      * ``env`` is only merged by the service when ``shell: true``; with
        ``shell: false`` (our case) task-level env is ignored by the service.
      * uploaded files are referenced by absolute destination path.
    """

    backend = "nebius"

    def __init__(
        self,
        base_url: str | None = None,
        iam_token: str | None = None,
        project: str | None = None,
        timeout: float = 120.0,
        poll_interval: float = 1.0,
    ):
        self.base_url = (
            base_url
            or os.environ.get("NEBIUS_SANDBOXES_BASE_URL")
            or DEFAULT_SANDBOXES_BASE_URL
        ).rstrip("/")
        self.iam_token = iam_token or os.environ.get("NEBIUS_IAM_TOKEN") or ""
        self.project = project or os.environ.get("NEBIUS_PROJECT") or ""
        self.timeout = timeout
        self.poll_interval = poll_interval

    def _request(self, method: str, path: str, payload: dict | None = None,
                 raw_body: bytes | None = None, timeout: float | None = None,
                 allowed: tuple[int, ...] = ()):
        """Perform one Sandboxes API call. Returns (body, headers, status).

        Statuses listed in `allowed` are returned to the caller instead of
        raising (used for 425 'result not ready yet' polling).
        """
        url = f"{self.base_url}{path}"
        data = raw_body if raw_body is not None else (
            json.dumps(payload).encode("utf-8") if payload is not None else None
        )
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.iam_token}")
        req.add_header("Project", self.project)
        if raw_body is not None:
            req.add_header("Content-Type", "application/octet-stream")
        else:
            req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        try:
            resp = urllib.request.urlopen(req, timeout=timeout or self.timeout)
            with resp:
                raw = resp.read()
                body = json.loads(raw.decode("utf-8")) if raw else {}
                headers = {k.lower(): v for k, v in resp.headers.items()}
            return body, headers, resp.status
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            if exc.code in allowed:
                headers = {k.lower(): v for k, v in exc.headers.items()}
                return {}, headers, exc.code
            raise SandboxError(
                f"Sandboxes API {method} {path} -> HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise SandboxError(f"Sandboxes API unreachable: {exc.reason}") from exc

    def _upload_file(self, content: str) -> str:
        body, _headers, _status = self._request(
            "POST", "/v1/files", raw_body=content.encode("utf-8")
        )
        uuid = body.get("uuid")
        if not uuid:
            raise SandboxError(
                f"unexpected file-upload response shape: {json.dumps(body)[:200]}"
            )
        return uuid

    def _spawn(self, payload: dict) -> str:
        body, headers, _status = self._request("POST", "/v1/instances", payload)
        location = headers.get("location", "")
        if not location:
            raise SandboxError(
                "instance spawn response missing Location header (async operation id); "
                f"body: {json.dumps(body)[:200]}"
            )
        return location.rstrip("/").rsplit("/", 1)[-1]

    def _poll_result(self, operation_id: str, deadline: float) -> dict:
        path = f"/v1/operations/{operation_id}/subprocesses/1"
        while True:
            body, headers, status = self._request("GET", path, allowed=(425,))
            if status == 425:
                if time.monotonic() > deadline:
                    raise SandboxError(
                        f"sandbox operation {operation_id} not ready before deadline"
                    )
                try:
                    delay = float(headers.get("retry-after", "").strip() or self.poll_interval)
                except ValueError:
                    delay = self.poll_interval
                time.sleep(delay)
                continue
            if "state" not in body or "stdout" not in body:
                raise SandboxError(
                    "unexpected Sandboxes result shape (no state/stdout); API may "
                    f"have drifted: {json.dumps(body)[:200]}"
                )
            state = body.get("state", {})
            if state.get("exit_code", -1) != -1 or state.get("timed_out"):
                return body
            if time.monotonic() > deadline:
                raise SandboxError(
                    f"sandbox operation {operation_id} still running before deadline"
                )
            time.sleep(self.poll_interval)

    @staticmethod
    def _decode_stream(stream: dict | None) -> str:
        stream = stream or {}
        value = stream.get("value", "")
        if stream.get("encoding") == "base64":
            try:
                return base64.b64decode(value).decode("utf-8", errors="replace")
            except Exception as exc:
                raise SandboxError(f"could not decode sandbox stream: {exc}") from exc
        return value

    def run(
        self,
        command: list[str],
        files: dict[str, str] | None = None,
        image: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> ExecutionResult:
        if not command:
            raise SandboxError("command must be a non-empty argv list")
        del env  # the service only merges env when shell=true; we run shell=false
        effective_timeout = timeout or self.timeout

        file_refs: dict[str, dict] = {}
        for rel_path, content in (files or {}).items():
            uuid = self._upload_file(content)
            dest = f"{DEFAULT_INSTANCE_CWD}/{rel_path.lstrip('/')}"
            file_refs[dest] = {"uuid": uuid}

        spawn_payload = {
            "command": command[0],
            "args": list(command[1:]),
            "shell": False,
            "image": image or "tag:python:3.12-slim",
            "disposable": True,
            "cwd": DEFAULT_INSTANCE_CWD,
            "files": {dest: {"uuid": ref["uuid"]} for dest, ref in file_refs.items()},
            "timeout": int(effective_timeout),
        }
        operation_id = self._spawn(spawn_payload)
        result = self._poll_result(
            operation_id, deadline=time.monotonic() + effective_timeout + 30
        )
        state = result.get("state", {})
        resources = result.get("resources", {})
        cost = resources.get("cost")
        return ExecutionResult(
            stdout=self._decode_stream(result.get("stdout")),
            stderr=self._decode_stream(result.get("stderr")),
            exit_code=int(state.get("exit_code", -1)),
            timed_out=bool(state.get("timed_out", False)),
            cost=float(cost) if cost is not None else None,
            backend=self.backend,
        )


def make_sandbox(
    backend: str,
    base_url: str | None = None,
    iam_token: str | None = None,
    project: str | None = None,
    timeout: float = 120.0,
) -> LocalSandbox | NebiusSandbox:
    if backend == "local":
        return LocalSandbox(timeout=timeout)
    if backend == "nebius":
        return NebiusSandbox(
            base_url=base_url, iam_token=iam_token, project=project, timeout=timeout
        )
    raise SandboxError(f"Unknown sandbox backend '{backend}' (use 'local' or 'nebius')")
