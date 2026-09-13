# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | ✅ |

## Reporting a vulnerability

Use GitHub's **Private vulnerability reporting** on this repository
(Security tab → Report a vulnerability). Please do not open public issues for
security problems.

Include: the command you ran, the component involved
(`nemocascade/client.py`, `nemocascade/sandbox.py`, `devtools/mock_server.py`),
and a minimal reproduction. You can expect an initial response within 7 days.

## Scope and honest boundaries

- **`LocalSandbox` is not a security boundary.** It executes model-generated
  code on the host as a subprocess with a scrubbed environment (API keys and
  other secrets are not passed through), but it has full host compute access.
  Only run untrusted tasks where the host is disposable. VM-level isolation is
  what the `nebius` backend is for.
- **Model-generated artifacts are untrusted input.** They are executed by
  design — that is the point of the tool — so treat every
  `--sandbox local` run like running a stranger's script.
- **`devtools/mock_server.py` binds to 127.0.0.1 with an ephemeral port and is
  for tests/demos only.** It executes commands from its request payloads and
  must never be exposed beyond localhost.
- Credentials are read from environment variables only
  (`NEBIUS_API_KEY`, `NEBIUS_IAM_TOKEN`, `NEBIUS_PROJECT`) and are never
  logged, written to reports, or passed into sandbox subprocesses.

## Out of scope

Vulnerabilities in Nebius Token Factory or NVIDIA's models themselves — report
those through Nebius's or NVIDIA's own security channels.
