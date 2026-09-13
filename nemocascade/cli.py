"""nemocascade command line interface."""

from __future__ import annotations

import argparse
import json
import re
import sys

from . import __version__
from .cascade import Cascade
from .client import (
    TokenFactoryClient,
    TokenFactoryError,
    resolve_ladder,
)
from .report import results_to_json, write_report
from .sandbox import SandboxError, make_sandbox
from .tasks import TaskFormatError, load_tasks


def _load_config(path: str | None) -> dict:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _maybe_mock(args) -> None:
    """When --mock is passed, spin up the in-repo mock of Token Factory +
    Sandboxes on 127.0.0.1 and point every client at it.

    The mock exists so the tool can be demonstrated and tested with zero
    credentials. It is clearly labeled in all output as a mock backend.
    """
    if not getattr(args, "mock", False):
        return
    import sys as _sys
    from pathlib import Path as _Path

    _repo_root = str(_Path(__file__).resolve().parent.parent)
    if _repo_root not in _sys.path:
        _sys.path.insert(0, _repo_root)

    import threading

    from devtools.mock_server import MockState, create_server

    state = MockState()
    server = create_server(state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    if host == "0.0.0.0":
        host = "127.0.0.1"
    base = f"http://{host}:{port}/v1"
    args.base_url = base
    args.sandbox_base_url = base.rsplit("/v1", 1)[0]
    args.api_key = "mock-key"
    args.iam_token = "mock-iam"
    args.project = "mock-project"
    print(
        f"[nemocascade] MOCK backend on {base} — canned responses, no network, "
        "no credentials. Live runs use --base-url https://api.tokenfactory.nebius.com/v1",
        file=sys.stderr,
    )


def build_cascade(args) -> Cascade:
    _maybe_mock(args)
    client = TokenFactoryClient(
        base_url=args.base_url,
        api_key=args.api_key,
        timeout=args.timeout,
    )
    ladder = resolve_ladder(client, _load_config(args.config))

    sandbox = make_sandbox(
        args.sandbox or ("nebius" if args.mock else "local"),
        base_url=args.sandbox_base_url,
        iam_token=args.iam_token,
        project=args.project,
        timeout=args.timeout,
    )
    return Cascade(client, ladder, sandbox,
                   temperature=getattr(args, "temperature", 0.2),
                   max_tokens=getattr(args, "max_tokens", 2048))


def cmd_models(args) -> int:
    cascade = build_cascade(args)
    print("Discovered Nemotron escalation ladder (cheapest first):")
    for tier in cascade.ladder:
        print(f"  {tier.tier:<7} {tier.model}")
    return 0


def cmd_run(args) -> int:
    tasks, _defaults = load_tasks(args.tasks)
    cascade = build_cascade(args)
    print(
        f"Running {len(tasks)} task(s) on ladder "
        f"{' -> '.join(t.tier for t in cascade.ladder)} "
        f"with sandbox backend '{getattr(cascade.sandbox, 'backend', '?')}'"
    )
    results = []
    selected = [t for t in tasks if not args.only or t.id in set(args.only)]
    if args.only and not selected:
        known = ", ".join(t.id for t in tasks)
        print(f"nemocascade: error: --only matched no tasks (have: {known})",
              file=sys.stderr)
        return 2
    for task in selected:
        result = cascade.run_task(task)
        results.append(result)
        state = "PASS" if result.success else "FAIL"
        solved_by = result.final_model or "-"
        print(f"  {task.id:<24} {state:<5} steps={len(result.steps)} solved_by={solved_by}")

    report = results_to_json(results)
    write_report(report, args.out, args.md_out)
    summary = report["summary"]
    print(
        f"Done: {summary['succeeded']}/{summary['tasks']} succeeded "
        f"({summary['success_rate']:.0%}); report -> {args.out}"
        + (f" + {args.md_out}" if args.md_out else "")
    )
    return 0 if summary["succeeded"] == summary["tasks"] else 1


def cmd_report(args) -> int:
    with open(args.report, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    from .report import json_to_markdown

    md = json_to_markdown(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(md)
    else:
        print(md)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nemocascade",
        description="Execution-verified cost cascade for Nemotron models on Nebius Token Factory.",
    )
    parser.add_argument("--version", action="version", version=f"nemocascade {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base-url", default=None,
                        help="Token Factory base URL (default: https://api.tokenfactory.nebius.com/v1)")
    common.add_argument("--api-key", default=None,
                        help="Token Factory API key (default: $NEBIUS_API_KEY)")
    common.add_argument("--config", default=None,
                        help="Optional JSON config with explicit ladder/tiers/prices")
    common.add_argument("--sandbox", choices=("local", "nebius"), default=None,
                        help="Sandbox backend (default: nebius REST with --mock, else local)")
    common.add_argument("--sandbox-base-url", dest="sandbox_base_url", default=None,
                        help="Sandboxes API base URL (default: https://api.tokenfactory.nebius.com/sandboxes)")
    common.add_argument("--iam-token", dest="iam_token", default=None,
                        help="Sandboxes IAM token (default: $NEBIUS_IAM_TOKEN)")
    common.add_argument("--project", default=None,
                        help="Sandboxes project id (default: $NEBIUS_PROJECT)")
    common.add_argument("--timeout", type=float, default=120.0)
    common.add_argument("--mock", action="store_true",
                        help="Run against the bundled in-process mock (no credentials needed)")

    sub = parser.add_subparsers(dest="command", required=True)

    p_models = sub.add_parser("models", parents=[common],
                              help="Show the discovered Nemotron ladder")
    p_models.set_defaults(func=cmd_models)

    p_run = sub.add_parser("run", parents=[common], help="Run a task suite")
    p_run.add_argument("--tasks", required=True, help="Path to a tasks JSON file")
    p_run.add_argument("--only", nargs="*", default=None, help="Restrict to task ids")
    p_run.add_argument("--out", default="report.json", help="Report JSON output path")
    p_run.add_argument("--md-out", dest="md_out", default=None,
                       help="Also write a Markdown report to this path")
    p_run.add_argument("--temperature", type=float, default=0.2)
    p_run.add_argument("--max-tokens", dest="max_tokens", type=int, default=2048)
    p_run.set_defaults(func=cmd_run)

    p_report = sub.add_parser("report", help="Render a Markdown report from report JSON")
    p_report.add_argument("--report", required=True, help="Path to report JSON")
    p_report.add_argument("--out", default=None, help="Write Markdown here (default: stdout)")
    p_report.set_defaults(func=cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (TokenFactoryError, SandboxError, TaskFormatError, OSError,
            json.JSONDecodeError, KeyError, TypeError, ValueError, re.error) as exc:
        print(f"nemocascade: error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
