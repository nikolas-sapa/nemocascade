# Demo video script — Nebius x NVIDIA Global AI Hackathon (≤3 min, narrated)

Target: the "Coding & Agentic Engineering" track (agents/tools in Token Factory
Sandboxes). Record at 1080p; speak plainly; every claim in this script is
backed by the repo. Total runtime target: 2:30–2:55.

## Shot list

**0:00–0:20 — Problem (talking head or slides)**
"Agent workloads usually run every step on one model. Run everything on a
premium model and you burn money on trivial steps. Run everything cheap and
mistakes reach production. nemocascade fixes this with one rule: nothing is
accepted until it *executes and passes* in a sandbox."

**0:20–0:40 — What it is (screen: README diagram)**
"nemocascade runs each task through a cost-ordered ladder of NVIDIA Nemotron
models on Nebius Token Factory — nano first. Every candidate answer is
executed against the task's checker in Token Factory Sandboxes. Pass, done.
Fail, escalate to the next tier with the verified failure attached."

**0:40–1:05 — Live demo, ladder discovery (terminal)**
```
python3 -m nemocascade.cli models --mock
```
Point out: the ladder is discovered from `GET /v1/models` at runtime — it
follows whatever Nemotron generations Token Factory serves; you can pin exact
ids in config. "The `--mock` flag runs against an in-repo mock of Token
Factory and Sandboxes so you can try it with zero credentials — the mock even
executes the sandboxes as real subprocesses. Now the real run."

**1:05–1:50 — Live demo, run (terminal)**
```
python3 -m nemocascade.cli run --mock --tasks tasks/tasks.json \
  --config config.example.json --out report.json --md-out report.md
```
Narrate the three lines of output as they appear:
- normalize-name: nano fails the checker → escalated to super → pass.
- total-value: solved at the cheapest tier, one call.
- balanced-brackets: nano and super both fail the interleaved-brackets case →
  ultra solves it.
"The failures are real executions — the report shows the checker's actual
output as evidence."

**1:50–2:25 — The report (screen: report.md rendered)**
Show the tier usage table (calls, tokens, pass/fail per tier) and one task's
evidence rows. "Every run produces this: per-tier cost breakdown, escalation
counts, and per-step sandbox evidence. Configure real per-token prices and the
cost line is dollars; without prices, nemocascade shows token counts and says
so — it never invents a dollar figure."

**2:25–2:50 — Architecture and track fit (slides or README)**
"The agentic loop here is the escalate-with-evidence cycle: the agent
observes a verified failure, feeds it back to a stronger model, and retries —
with every step's receipts in the report. Zero third-party dependencies: the
OpenAI-compatible chat client, the async Sandboxes client (upload → spawn →
poll), the cascade engine, the reporter — all stdlib. It uses two Nebius
surfaces — Token Factory inference across Nemotron nano, super and ultra, and
Token Factory Sandboxes for verification — and the whole behavior is covered
by 48 tests. Same code runs `--sandbox local` or `--sandbox nebius`. Repo and
setup instructions are in the submission. Thanks for watching."

## Recording notes

- Rehearse the two terminal demos once; both run in <15 seconds.
- If recording before the live-key smoke test (see SUBMISSION_CHECKLIST.md),
  keep the mock clearly labeled on screen (it prints `MOCK backend` on
  stderr — leave that visible; honesty reads well). The mock is a stand-in
  for the screen demo; the live smoke test in the checklist is mandatory
  before quoting any live numbers in the Devpost body.
- Optional stronger take if the live smoke test passes: re-record the run
  segment with `--sandbox nebius` against the real endpoint and say so.
