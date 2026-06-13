"""CLI wiring for the `kento diagnose [NAME] [--json]` verb.

The library does the work (kento.diagnose.run_diagnostics / format_diagnostics);
the CLI just routes args, prints, and maps problem_count -> exit code:
  problem_count > 0 -> exit 1, else exit 0.
A name that doesn't resolve raises InstanceNotFoundError (a KentoError) which
the shared _handle path turns into "Error: ..." on stderr + exit 1.
"""
import json

import pytest

import kento.diagnose as kdiag

import kento_cli as cli


def _clean_report():
    return {"checks": [
        {"category": "host", "severity": "ok", "scope": "host",
         "message": "all good", "remediation": ""},
    ], "problem_count": 0, "instances_scanned": 2}


def _problem_report():
    return {"checks": [
        {"category": "orphan", "severity": "warn", "scope": "host",
         "message": "orphaned vmid 101", "remediation": "kento destroy -f"},
    ], "problem_count": 1, "instances_scanned": 2}


def test_diagnose_clean_prints_formatted_and_exits_0(capsys, monkeypatch):
    monkeypatch.setattr(kdiag, "run_diagnostics", lambda name=None: _clean_report())
    monkeypatch.setattr(kdiag, "format_diagnostics", lambda r: "FORMATTED-CLEAN")
    with pytest.raises(SystemExit) as exc:
        cli.main(["diagnose"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "FORMATTED-CLEAN"


def test_diagnose_problems_exit_1(capsys, monkeypatch):
    monkeypatch.setattr(kdiag, "run_diagnostics", lambda name=None: _problem_report())
    monkeypatch.setattr(kdiag, "format_diagnostics", lambda r: "FORMATTED-PROBLEMS")
    with pytest.raises(SystemExit) as exc:
        cli.main(["diagnose"])
    assert exc.value.code == 1
    assert capsys.readouterr().out.strip() == "FORMATTED-PROBLEMS"


def test_diagnose_json_outputs_report_dict(capsys, monkeypatch):
    report = _clean_report()
    monkeypatch.setattr(kdiag, "run_diagnostics", lambda name=None: report)
    # format_diagnostics must NOT be used on the --json path
    monkeypatch.setattr(kdiag, "format_diagnostics",
                        lambda r: pytest.fail("format_diagnostics called on --json path"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["diagnose", "--json"])
    assert exc.value.code == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed == report


def test_diagnose_json_problem_count_exit_1(capsys, monkeypatch):
    report = _problem_report()
    monkeypatch.setattr(kdiag, "run_diagnostics", lambda name=None: report)
    with pytest.raises(SystemExit) as exc:
        cli.main(["diagnose", "--json"])
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out) == report


def test_diagnose_name_passed_to_run_diagnostics(capsys, monkeypatch):
    seen = {}

    def fake(name=None):
        seen["name"] = name
        return _clean_report()

    monkeypatch.setattr(kdiag, "run_diagnostics", fake)
    monkeypatch.setattr(kdiag, "format_diagnostics", lambda r: "x")
    with pytest.raises(SystemExit) as exc:
        cli.main(["diagnose", "somename"])
    assert exc.value.code == 0
    assert seen["name"] == "somename"


def test_diagnose_no_name_passes_none(capsys, monkeypatch):
    seen = {}

    def fake(name=None):
        seen["name"] = name
        return _clean_report()

    monkeypatch.setattr(kdiag, "run_diagnostics", fake)
    monkeypatch.setattr(kdiag, "format_diagnostics", lambda r: "x")
    with pytest.raises(SystemExit) as exc:
        cli.main(["diagnose"])
    assert exc.value.code == 0
    assert seen["name"] is None


def test_diagnose_unknown_name_errors_exit_1(capsys, monkeypatch):
    from kento import InstanceNotFoundError

    def boom(name=None):
        raise InstanceNotFoundError("no such instance: ghost")

    monkeypatch.setattr(kdiag, "run_diagnostics", boom)
    with pytest.raises(SystemExit) as exc:
        cli.main(["diagnose", "ghost"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("Error:")
    assert "ghost" in err


def test_diagnose_is_top_level_only(capsys):
    """diagnose must NOT be a subcommand of lxc or vm."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["lxc", "diagnose"])
    # argparse rejects the unknown subcommand with exit code 2
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        cli.main(["vm", "diagnose"])
    assert exc.value.code == 2


def test_diagnose_listed_in_top_help(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert "diagnose" in out
