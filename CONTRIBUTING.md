# Contributing to nemocascade

Thanks for considering a contribution. This is a hackathon-born project and we
keep it small and dependency-free on purpose.

## Ground rules

- **Zero third-party runtime dependencies.** The package must keep running on a
  stock Python 3.10+ interpreter. If you need a library, make it an optional
  dev extra or argue for it in an issue first.
- **Honest scope labels.** Claims about what runs where (mock vs live Nebius)
  must stay accurate. Anything tested only against the in-repo mock must be
  described as such.
- **No fabricated results.** Reports may only contain numbers the code actually
  produced. Pricing is always configurable and never invented.

## Development setup

```bash
git clone https://github.com/nikolas-sapa/nemocascade.git
cd nemocascade
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python3 -m pytest tests/ -q
```

The test suite runs entirely against `devtools/mock_server.py` — no Nebius
account required.

## Try it

```bash
python3 -m nemocascade.cli run --mock --tasks tasks/tasks.json \
  --config config.example.json --out report.json --md-out report.md
```

## Pull requests

- Keep diffs minimal and in the style of the surrounding code.
- Add or update tests for behavior changes. New mock behaviors go in
  `devtools/mock_server.py` next to the existing scripted tiers.
- If you touch the Sandboxes client, note that `NebiusSandbox` is contract-
  tested against the mock only — say so in the PR description and keep failure
  modes loud (raise on unexpected response shapes; never guess defaults).
- CI: `python3 -m pytest tests/ -q` must pass.

## Reporting bugs

Open a GitHub issue with the command you ran, the full output, and your Python
version. For security matters, see [SECURITY.md](SECURITY.md) instead.
