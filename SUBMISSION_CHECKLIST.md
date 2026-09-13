# SUBMISSION CHECKLIST — Nebius x NVIDIA Global AI Hackathon

Devpost: https://nebiusglobalaihackathon.devpost.com — deadline **Oct 30, 2026,
10:00 am PT**. Track: **Coding & Agentic Engineering**.

The agent (Agent B) built everything in this repo. The steps below need a human
because they involve account creation, credentials, and payments decisions —
do NOT hand credentials to the agent.

## 1. Accounts (human-only; ~20 min)

- [ ] Devpost account (the human's own — required to submit).
- [ ] Nebius account at tokenfactory.nebius.com (Google/GitHub login). Free
      $1 trial credit on signup; consider joining the **Nebius Builder
      Program** linked from the hackathon page for hackathon credits
      (Token Factory + Tavily). Signing up = accepting Nebius ToS — your call.
- [ ] Optional: YouTube account for the demo video upload.

Eligibility check: entrant must be above legal age of majority; residents of
Brazil, Quebec, Russia, Crimea, Cuba, Iran, North Korea and OFAC-sanctioned
jurisdictions are excluded. Solo entry is allowed.

## 2. Local verification (human, ~10 min)

```bash
cd nemocascade
python3 -m pytest tests/ -q                 # expect: 48 passed
python3 -m nemocascade.cli run --mock --tasks tasks/tasks.json \
  --config config.example.json --out report.json --md-out report.md
```

Take a screenshot of the terminal output (ladder discovery + the 3-task run)
— the Devpost submission form expects screenshots and there are none in the
repo by design (they should show YOUR machine).

## 3. Live smoke test (~15 min, small cost from trial credits) — MANDATORY

This is the one thing the mock cannot prove: the real API contract. The chat
client targets the OpenAI-compatible `/v1` contract. The Sandboxes backend
implements the async ConTree contract (upload files → spawn instance → poll
`/v1/operations/<id>/subprocesses/1`) from the published API reference —
**it has never talked to the real service**, so this test is required before
recording the video or quoting any live number.

```bash
export NEBIUS_API_KEY=...          # tokenfactory.nebius.com
export NEBIUS_IAM_TOKEN=...        # for Sandboxes
export NEBIUS_PROJECT=...          # your project id

python3 -m nemocascade.cli models                          # discovers real Nemotron ids
python3 -m nemocascade.cli run --tasks tasks/tasks.json \
  --config config.example.json --sandbox nebius \
  --out live-report.json --md-out live-report.md
```

- [ ] Ladder discovery returns real Nemotron ids (if a tier keyword doesn't
      match the live catalog, pin the exact id in a config JSON — see
      `resolve_ladder` in `nemocascade/client.py`).
- [ ] All 3 demo tasks pass on the live run; escalation behaves like the mock.
- [ ] If the Sandboxes beta API rejects a request or returns an unexpected
      shape, `NebiusSandbox` raises with the payload in the message — adjust
      the flow in `nemocascade/sandbox.py` (upload/spawn/poll are separate
      clearly-named methods) and note any change in the Devpost "additional
      info" for transparency.
- [ ] Update `config.example.json` prices from tokenfactory.nebius.com if you
      want a real dollar figure in the report.

## 4. Public repo (human, ~10 min)

- [ ] Create a **public GitHub repo** under the human's account, push this
      folder. License is already MIT (required: open-source license in the
      repo About).
- [ ] Add the license in the repo About field, description:
      "Execution-verified cost cascade for NVIDIA Nemotron on Nebius Token Factory".
- [ ] The project was built fresh during the submission window (started
      2026-09-13, after the Aug 26 start) — no pre-existing-project
      explanation is needed. Keep the git history clean from here on.

## 5. Demo video (human, ~45 min)

- [ ] Follow `DEMO.md` shot list (≤3 min, narrated, screen recording).
- [ ] Upload to YouTube (public or unlisted) — Devpost requires a link.

## 6. Devpost submission (human, ~20 min)

- [ ] Join the hackathon on Devpost; enter solo, select **Coding & Agentic
      Engineering**.
- [ ] Submit with: project title/tagline, description (adapt README "Why" +
      "What was tested where" sections verbatim — they are written to be
      honest about mock vs live), the public repo URL, demo video URL,
      "Built with": Nebius Token Factory, Token Factory Sandboxes, NVIDIA
      Nemotron (nano/super/ultra), Python.
- [ ] Optional feedback fields: the "Most Valuable Feedback" award ($100 ×10)
      is granted for feedback on the tools used — write 3–4 concrete sentences
      about Token Factory/Sandboxes from the smoke test while it's fresh.
- [ ] Optional: City Winner Awards ($500 ×20) require attending a
      **Builders & Brews** in-person event in one of the 20 listed cities —
      check the events list before travel; skip if none is near you.
- [ ] Double-check the final deadline: **Oct 30, 2026, 10:00 am PT**.

## 7. After submission

- [ ] Judging runs Dec 1–15; winners ~Jan 11, 2027. Any prize payout/KYC/tax
      steps are human-only — never share bank/tax details with the agent.
- [ ] If you win: Devpost/Nebius will contact the account holder. Stop and
      handle payout steps yourself.
