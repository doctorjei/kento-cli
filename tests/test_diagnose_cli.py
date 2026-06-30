"""CLI wiring for `kento diagnose [NAME] [--json]`, re-pointed (Blocks 18 + 22).

Phase 6 (Block 18) re-pointed the handler off `format_diagnostics`; Block 22
collapses BOTH scopes onto the SAME typed entry point — the module-level
`kento.diagnose(name)` FUNCTION (the shadow-safe entry point — NOT the
`kento.diagnose` submodule) -> a typed `Diagnosis`. Classes-only across the
seam: the handler no longer imports any library internals (no
`run_diagnostics`, no `diagnosis_from_report`, no `importlib.import_module`).
  * NO name (host-wide): `kento.diagnose(None)`, `instances_scanned =
    len(Instance.list())`.
  * a NAME: `kento.diagnose(name)` (the library narrows + projects unfiltered —
    the named wire is host+instance checks), `instances_scanned = 1`.
Then prints the Block-17 projection (`diagnosis_to_json` / `diagnosis_to_human`)
and exits `1 if diag.problems else 0`. An unresolved name raises
InstanceNotFoundError (from the library) -> the shared _handle turns it into
"Error: ..." + exit 1.

These tests assert the WIRING (the single entry point, the count, the
json-vs-human branch, the exit code, error mapping) AND that no dict / library
internal crosses the seam. The byte-identical wire produced by the projection
is pinned by test_projection_golden.py.
"""
import importlib
import json

import pytest

import kento
from kento import Ok  # S4: Instance.list() returns Result; stubs wrap in Ok
import kento_cli as cli
from kento_cli import _projection  # noqa: F401  (register cli._projection)

_diagnose_mod = importlib.import_module("kento.diagnose")


# A clean and a problem report in the run_diagnostics wire shape.
def _clean_report():
    return {"checks": [
        {"category": "apparmor", "severity": "ok", "scope": "host",
         "message": "all good", "remediation": None},
    ], "problem_count": 0, "instances_scanned": 2}


def _problem_report():
    return {"checks": [
        {"category": "orphan", "severity": "warn", "scope": "host",
         "message": "orphaned vmid 101", "remediation": "kento destroy -f"},
    ], "problem_count": 1, "instances_scanned": 2}


def _typed(report):
    from kento._diagnosis import diagnosis_from_report
    return diagnosis_from_report(report)


# --------------------------------------------------------------------------- #
# Host-wide scan (no name) -> kento.diagnose() the FUNCTION.
# --------------------------------------------------------------------------- #


def test_diagnose_no_name_uses_module_function(capsys, monkeypatch):
    """No name -> the module-level kento.diagnose() fn; instances_scanned from
    len(Instance.list()); human output; exit 0 (clean)."""
    called = {}

    def fake_diagnose(name=None):
        called["fn"] = True
        called["name"] = name
        return _typed(_clean_report())

    monkeypatch.setattr(kento, "diagnose", fake_diagnose)
    monkeypatch.setattr(kento.Instance, "list",
                        classmethod(lambda cls: Ok(value=[object(), object()])))
    monkeypatch.setattr(cli._projection, "diagnosis_to_human",
                        lambda diag, *, instances_scanned: f"H:{instances_scanned}")
    with pytest.raises(SystemExit) as exc:
        cli.main(["diagnose"])
    assert exc.value.code == 0
    assert called["fn"] is True
    assert called["name"] is None  # host-wide -> name=None
    assert capsys.readouterr().out.strip() == "H:2"


def test_diagnose_no_name_json_branch_and_exit_1(capsys, monkeypatch):
    """No name + --json + problems -> json projection + exit 1."""
    monkeypatch.setattr(kento, "diagnose",
                        lambda name=None: _typed(_problem_report()))
    monkeypatch.setattr(kento.Instance, "list",
                        classmethod(lambda cls: Ok(value=[object(), object()])))
    monkeypatch.setattr(cli._projection, "diagnosis_to_human",
                        lambda *a, **k: pytest.fail("human path used on --json"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["diagnose", "--json"])
    assert exc.value.code == 1
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["problem_count"] == 1
    assert parsed["instances_scanned"] == 2


# --------------------------------------------------------------------------- #
# Named scan -> the SAME typed kento.diagnose(name) fn, instances_scanned == 1.
# Block 22: no submodule reach, no dict crosses the seam.
# --------------------------------------------------------------------------- #


def test_diagnose_name_uses_module_function_with_count_1(capsys, monkeypatch):
    seen = {}

    def fake_diagnose(name=None):
        seen["name"] = name
        return _typed(_clean_report())

    monkeypatch.setattr(kento, "diagnose", fake_diagnose)
    # The handler must NOT reach the submodule's run_diagnostics on the named
    # path (Block 22 removed that reach — it is the dict-crossing violation).
    monkeypatch.setattr(
        _diagnose_mod, "run_diagnostics",
        lambda *a, **k: pytest.fail("submodule run_diagnostics reached"))
    monkeypatch.setattr(cli._projection, "diagnosis_to_human",
                        lambda diag, *, instances_scanned: f"N:{instances_scanned}")
    with pytest.raises(SystemExit) as exc:
        cli.main(["diagnose", "somename"])
    assert exc.value.code == 0
    assert seen["name"] == "somename"
    assert capsys.readouterr().out.strip() == "N:1"


def test_diagnose_name_passes_diagnosis_not_dict(monkeypatch):
    """The handler must hand the projection a typed Diagnosis, never a dict."""
    from kento import Diagnosis

    captured = {}
    monkeypatch.setattr(kento, "diagnose",
                        lambda name=None: _typed(_clean_report()))

    def capture(diag, *, instances_scanned):
        captured["diag"] = diag
        return "x"

    monkeypatch.setattr(cli._projection, "diagnosis_to_human", capture)
    with pytest.raises(SystemExit):
        cli.main(["diagnose", "somename"])
    assert isinstance(captured["diag"], Diagnosis)
    assert not isinstance(captured["diag"], dict)


def test_diagnose_name_problems_exit_1(capsys, monkeypatch):
    monkeypatch.setattr(kento, "diagnose",
                        lambda name=None: _typed(_problem_report()))
    monkeypatch.setattr(cli._projection, "diagnosis_to_human",
                        lambda diag, *, instances_scanned: "x")
    with pytest.raises(SystemExit) as exc:
        cli.main(["diagnose", "somename"])
    assert exc.value.code == 1


def test_diagnose_unknown_name_errors_exit_1(capsys, monkeypatch):
    from kento import InstanceNotFoundError

    def boom(name=None):
        raise InstanceNotFoundError("no instance named 'ghost'.")

    monkeypatch.setattr(kento, "diagnose", boom)
    with pytest.raises(SystemExit) as exc:
        cli.main(["diagnose", "ghost"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("Error:")
    assert "ghost" in err


# --------------------------------------------------------------------------- #
# Wire fidelity end-to-end (real projection, real mapper).
# --------------------------------------------------------------------------- #


def test_diagnose_no_name_json_byte_identical_to_legacy(capsys, monkeypatch):
    """The re-pointed --json host scan equals json.dumps(report, indent=2) for
    the report run_diagnostics(None) would have returned (instances_scanned from
    len(Instance.list()) == the report's count)."""
    report = _problem_report()  # instances_scanned == 2
    monkeypatch.setattr(_diagnose_mod, "run_diagnostics",
                        lambda name=None: report)
    # kento.diagnose() runs the real submodule call internally; with run_diagnostics
    # stubbed it sees `report`. Instance.list() must agree on the count (2).
    monkeypatch.setattr(kento.Instance, "list",
                        classmethod(lambda cls: Ok(value=[object(), object()])))
    with pytest.raises(SystemExit):
        cli.main(["diagnose", "--json"])
    out = capsys.readouterr().out
    assert json.loads(out) == report
    assert out == json.dumps(report, indent=2) + "\n"


# --------------------------------------------------------------------------- #
# Registration / help (unchanged from before the re-point).
# --------------------------------------------------------------------------- #


def test_diagnose_is_top_level_only(capsys):
    """diagnose must NOT be a subcommand of lxc or vm."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["lxc", "diagnose"])
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        cli.main(["vm", "diagnose"])
    assert exc.value.code == 2


def test_diagnose_listed_in_top_help(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert "diagnose" in out
