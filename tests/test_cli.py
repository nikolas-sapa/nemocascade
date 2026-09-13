import json

from conftest import TASKS, TASKS_NEGATIVE
from nemocascade.cli import main


def test_cli_run_mock_end_to_end(tmp_path, capsys):
    out = tmp_path / "report.json"
    md = tmp_path / "report.md"
    rc = main(["run", "--mock", "--tasks", str(TASKS),
               "--out", str(out), "--md-out", str(md)])
    assert rc == 0
    report = json.loads(out.read_text())
    assert report["summary"]["tasks"] == 3
    assert report["summary"]["succeeded"] == 3
    assert report["summary"]["escalated"] >= 1  # the demo story shows escalation
    ids = {t["task_id"] for t in report["tasks"]}
    assert ids == {"normalize-name", "total-value", "balanced-brackets"}
    md_text = md.read_text()
    assert "# nemocascade run report" in md_text
    assert "balanced-brackets — PASS" in md_text
    err = capsys.readouterr().err
    assert "MOCK backend" in err  # mock runs must always announce themselves


def test_cli_models_mock(capsys):
    rc = main(["models", "--mock"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Discovered Nemotron escalation ladder" in captured.out
    assert "nvidia/nemotron-3-ultra-253b-instruct" in captured.out


def test_cli_run_failure_returns_nonzero(tmp_path):
    out = tmp_path / "negative-report.json"
    rc = main(["run", "--mock", "--tasks", str(TASKS_NEGATIVE), "--out", str(out)])
    assert rc == 1
    report = json.loads(out.read_text())
    assert report["summary"]["succeeded"] == 0
    assert report["summary"]["tasks"] == 2


def test_cli_report_subcommand(tmp_path, capsys):
    out = tmp_path / "report.json"
    main(["run", "--mock", "--tasks", str(TASKS), "--out", str(out)])
    capsys.readouterr()
    rc = main(["report", "--report", str(out)])
    assert rc == 0
    assert "# nemocascade run report" in capsys.readouterr().out


def test_cli_missing_tasks_file_clean_error(tmp_path):
    rc = main(["run", "--mock", "--tasks", str(tmp_path / "nope.json"),
               "--out", str(tmp_path / "r.json")])
    assert rc == 2


def test_cli_only_flag_filters_tasks(tmp_path):
    out = tmp_path / "filtered.json"
    rc = main(["run", "--mock", "--tasks", str(TASKS), "--only", "total-value",
               "--out", str(out)])
    assert rc == 0
    report = json.loads(out.read_text())
    assert [t["task_id"] for t in report["tasks"]] == ["total-value"]
