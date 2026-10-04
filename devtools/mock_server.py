"""In-process mock of Nebius Token Factory (OpenAI-compatible) + Sandboxes.

Purpose: let nemocascade be demonstrated, tested, and CI-run with zero
credentials. The mock binds 127.0.0.1 on an ephemeral port and implements the
Sandboxes async contract (upload files -> spawn instance -> 425/200 polling):

* GET  /v1/models                              -> a Nemotron catalog
* POST /v1/chat/completions                    -> scripted per (keyword, tier)
* POST /v1/files                               -> 201 {uuid, sha256, size}
* POST /v1/instances                           -> 201 + Location operation id
* GET  /v1/operations/<id>/subprocesses/1      -> 425 once, then 200 InstanceResult

The mock executes spawned commands as real subprocesses (scrubbed env), so
verifier verdicts are honest: a canned "wrong" answer genuinely fails its
check.py inside the mock sandbox.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import uuid as uuid_module
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CATALOG = [
    {"id": "nvidia/nemotron-3-nano-4b-instruct", "object": "model"},
    {"id": "nvidia/nemotron-3-nano-4b-instruct-fast", "object": "model"},
    {"id": "nvidia/nemotron-3-super-49b-instruct", "object": "model"},
    {"id": "nvidia/nemotron-3-ultra-253b-instruct", "object": "model"},
    {"id": "deepseek-ai/DeepSeek-R1-0528", "object": "model"},
]

USAGE = {
    "nano": {"prompt_tokens": 240, "completion_tokens": 90},
    "super": {"prompt_tokens": 610, "completion_tokens": 210},
    "ultra": {"prompt_tokens": 1180, "completion_tokens": 460},
}

NANO_NORMALIZE = """import re

def normalize_name(value: str) -> str:
    value = value.lower()
    return re.sub(r"\\s+", "-", value.strip())
"""

SUPER_NORMALIZE = """import re

def normalize_name(value: str) -> str:
    value = re.sub(r"\\s+", "-", value.strip().lower())
    value = re.sub(r"-{2,}", "-", value)
    return value.strip("-")
"""

NANO_TOTAL = """def total_value(items_csv: str) -> float:
    total = 0.0
    for line in items_csv.splitlines():
        if not line.strip():
            continue
        _name, quantity, price = line.split(",")
        total += int(quantity) * float(price)
    return total
"""

NANO_BALANCED = """def is_balanced(s: str) -> bool:
    depth = 0
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0
"""

SUPER_BALANCED = """def is_balanced(s: str) -> bool:
    stack = []
    pairs = {")": "(", "]": "[", "}": "{"}
    for ch in s:
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack:
                return False
            stack.pop()
    return not stack
"""

ULTRA_BALANCED = """def is_balanced(s: str) -> bool:
    pairs = {")": "(", "]": "[", "}": "{"}
    stack = []
    for ch in s:
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack
"""

BROKEN = """def broken():
    return 42
"""

PROSE = (
    "My approach: I would validate the bracket sequence with a stack, pushing "
    "openers and checking that each closer matches the most recent opener. "
    "(No code provided by design.)"
)


def _fence(code: str) -> str:
    return f"```python\n{code}```"


def _stream(text: str) -> dict:
    """InstanceResult StreamRepr (base64-encoded, per the Sandboxes contract)."""
    return {
        "value": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        "encoding": "base64",
        "truncated": False,
    }


# keyword -> tier -> response content
BEHAVIORS: dict[str, dict[str, str]] = {
    "normalize_name": {
        "nano": _fence(NANO_NORMALIZE),
        "super": _fence(SUPER_NORMALIZE),
        "ultra": _fence(SUPER_NORMALIZE),
    },
    "total_value": {
        "nano": _fence(NANO_TOTAL),
        "super": _fence(NANO_TOTAL),
        "ultra": _fence(NANO_TOTAL),
    },
    "is_balanced": {
        "nano": _fence(NANO_BALANCED),
        "super": _fence(SUPER_BALANCED),
        "ultra": _fence(ULTRA_BALANCED),
    },
    "prose only": {
        "nano": PROSE,
        "super": PROSE,
        "ultra": PROSE,
    },
    "impossible": {
        "nano": _fence(BROKEN),
        "super": _fence(BROKEN),
        "ultra": _fence(BROKEN),
    },
}


def _tier_of(model_id: str) -> str:
    lowered = model_id.lower()
    for tier in ("nano", "super", "ultra"):
        if tier in lowered:
            return tier
    return "nano"


def _classify(keyword: str, user_text: str) -> str | None:
    return keyword if keyword.lower() in user_text.lower() else None


class MockState:
    """Records requests so tests and demo output can assert on them."""

    def __init__(self):
        self.lock = threading.Lock()
        self.chat_calls: list[dict] = []
        self.file_uploads: list[str] = []          # uploaded contents
        self.spawn_calls: list[dict] = []          # instance spawn payloads
        self.file_store: dict[str, str] = {}       # uuid -> content
        self.operations: dict[str, dict] = {}      # op id -> {"polls": int, "result": dict}

    def record_operation(self, result: dict) -> str:
        op_id = str(uuid_module.uuid4())
        self.operations[op_id] = {"polls": 0, "result": result}
        return op_id


def create_server(state: MockState | None = None) -> ThreadingHTTPServer:
    shared_state: MockState = state or MockState()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence request logging
            pass

        def _send(self, status: int, body: dict) -> None:
            raw = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _authed(self) -> bool:
            auth = self.headers.get("Authorization", "")
            return auth.startswith("Bearer ") and len(auth) > len("Bearer ")

        def _handle_file_upload(self, raw: bytes) -> None:
            if not self._authed() or not self.headers.get("Project"):
                self._send(401, {"error": {"message": "missing IAM token or project"}})
                return
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                self._send(400, {"error": {"message": "file content must be utf-8 text"}})
                return
            file_uuid = str(uuid_module.uuid4())
            with shared_state.lock:
                shared_state.file_uploads.append(content)
                shared_state.file_store[file_uuid] = content
            self._send(201, {
                "uuid": file_uuid,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "size": len(content.encode("utf-8")),
            })

        def do_GET(self):
            if self.path == "/v1/models":
                if not self._authed():
                    self._send(401, {"error": {"message": "missing bearer token"}})
                    return
                self._send(200, {"object": "list", "data": CATALOG})
                return
            if self.path.startswith("/v1/operations/") and \
                    self.path.endswith("/subprocesses/1"):
                if not self._authed() or not self.headers.get("Project"):
                    self._send(401, {"error": {"message": "missing IAM token or project"}})
                    return
                op_id = self.path[len("/v1/operations/"):-len("/subprocesses/1")]
                with shared_state.lock:
                    op = shared_state.operations.get(op_id)
                    if op is None:
                        self._send(404, {"error": {"message": "unknown operation"}})
                        return
                    op["polls"] += 1
                    ready = op["polls"] > 1  # exercise the 425-not-ready path once
                if not ready:
                    self.send_response(425)
                    self.send_header("Retry-After", "0.05")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self._send(200, op["result"])
                return
            self._send(404, {"error": {"message": f"no route {self.path}"}})

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            if self.path == "/v1/files":
                self._handle_file_upload(raw)
                return
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except json.JSONDecodeError:
                self._send(400, {"error": {"message": "invalid JSON"}})
                return

            if self.path == "/v1/chat/completions":
                if not self._authed():
                    self._send(401, {"error": {"message": "missing bearer token"}})
                    return
                model = payload.get("model", "")
                tier = _tier_of(model)
                user_text = " ".join(
                    m.get("content", "") for m in payload.get("messages", [])
                    if m.get("role") == "user"
                )
                keyword = next(
                    (k for k in BEHAVIORS if _classify(k, user_text)), None
                )
                content = BEHAVIORS.get(keyword, {}).get(tier, PROSE)
                with shared_state.lock:
                    shared_state.chat_calls.append({
                        "model": model,
                        "keyword": keyword,
                        "messages": payload.get("messages", []),
                    })
                self._send(200, {
                    "id": "chatcmpl-mock-1",
                    "object": "chat.completion",
                    "created": 0,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }],
                    "usage": dict(USAGE[tier]),
                })
            elif self.path == "/v1/instances":
                if not self._authed() or not self.headers.get("Project"):
                    self._send(401, {"error": {"message": "missing IAM token or project"}})
                    return
                command = payload.get("command")
                args = payload.get("args") or []
                timeout = float(payload.get("timeout") or 30)
                if not command:
                    self._send(400, {"error": {"message": "command required"}})
                    return
                with shared_state.lock:
                    shared_state.spawn_calls.append(payload)
                    file_store = dict(shared_state.file_store)
                with tempfile.TemporaryDirectory(prefix="mock-sandbox-") as tmp:
                    work_dir = os.path.join(tmp, "work")
                    os.makedirs(work_dir, exist_ok=True)
                    for dest_path, ref in (payload.get("files") or {}).items():
                        content = file_store.get((ref or {}).get("uuid"), "")
                        rel = dest_path.lstrip("/")
                        dest = os.path.realpath(os.path.join(tmp, rel))
                        if dest != os.path.realpath(tmp) and \
                                not dest.startswith(os.path.realpath(tmp) + os.sep):
                            self._send(400, {"error": {"message": "path escapes sandbox"}})
                            return
                        os.makedirs(os.path.dirname(dest) or tmp, exist_ok=True)
                        with open(dest, "w", encoding="utf-8") as handle:
                            handle.write(content)
                    cwd = work_dir if payload.get("cwd") == "/work" else tmp
                    try:
                        proc = subprocess.run(
                            [command] + list(args), cwd=cwd, capture_output=True,
                            text=True, timeout=timeout, check=False,
                            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                                 "PYTHONIOENCODING": "utf-8"},
                        )
                        result = {
                            "stdout": _stream(proc.stdout),
                            "stderr": _stream(proc.stderr),
                            "state": {"exit_code": proc.returncode,
                                      "timed_out": False, "pid": 1,
                                      "signal": -1, "continued": False,
                                      "core_dump": False, "stopped": False},
                            "resources": {"cost": 0.0021},
                        }
                    except subprocess.TimeoutExpired:
                        result = {
                            "stdout": _stream(""),
                            "stderr": _stream("timeout"),
                            "state": {"exit_code": -1, "timed_out": True,
                                      "pid": 1, "signal": -1, "continued": False,
                                      "core_dump": False, "stopped": False},
                            "resources": {"cost": 0.0021},
                        }
                op_id = shared_state.record_operation(result)
                response = dict(payload)
                response["uuid"] = str(uuid_module.uuid4())
                response["result"] = None
                raw = json.dumps(response).encode("utf-8")
                self.send_response(201)
                self.send_header("Location", f"/v1/operations/{op_id}")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            else:
                self._send(404, {"error": {"message": f"no route {self.path}"}})

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)
