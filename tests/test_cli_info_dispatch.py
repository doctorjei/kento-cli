"""The `info`/`inspect` handler re-pointed onto the typed lib + projection.

Block 18 (Phase 6): the handler resolves `Instance.get(name)` (scope-narrowed to
SystemContainer/VirtualMachine) and prints the Block-17 projection
(`instance_to_json` / `instance_to_human`). The library no longer builds the
strings. These tests assert the WIRING (resolve -> project -> print, the
json-vs-human branch, scope->class, and InstanceNotFound -> Error/exit 1);
byte-identical output is pinned by test_projection_golden.py.
"""
import pytest

import kento
import kento_cli as cli
from kento_cli import main
from kento_cli import _projection  # noqa: F401  (register cli._projection)


def _stub_get(monkeypatch, *, captured=None):
    """Stub the three get() entry points to return a sentinel, recording which
    class was used and the name passed."""
    sentinel = object()

    def make(cls_label):
        def fake_get(name):
            if captured is not None:
                captured["cls"] = cls_label
                captured["name"] = name
            return sentinel
        return fake_get

    monkeypatch.setattr(kento.Instance, "get", classmethod(
        lambda cls, name: make("base")(name)))
    monkeypatch.setattr(kento.SystemContainer, "get", classmethod(
        lambda cls, name: make("lxc")(name)))
    monkeypatch.setattr(kento.VirtualMachine, "get", classmethod(
        lambda cls, name: make("vm")(name)))
    return sentinel


def test_dispatch_info_human_prints_projection(capsys, monkeypatch):
    monkeypatch.setattr(kento, "require_root", lambda: None)
    monkeypatch.setattr(kento, "validate_name", lambda *a, **k: None)
    sentinel = _stub_get(monkeypatch)
    seen = {}

    def fake_human(inst, *, verbose=False):
        seen["inst"] = inst
        seen["verbose"] = verbose
        return "HUMAN-INFO-BLOCK"

    monkeypatch.setattr(cli._projection, "instance_to_human", fake_human)
    monkeypatch.setattr(cli._projection, "instance_to_json",
                        lambda *a, **k: pytest.fail("json path used"))
    main(["info", "anything"])
    assert capsys.readouterr().out.strip() == "HUMAN-INFO-BLOCK"
    assert seen["inst"] is sentinel
    assert seen["verbose"] is False


def test_dispatch_info_json_branch_and_verbose(capsys, monkeypatch):
    monkeypatch.setattr(kento, "require_root", lambda: None)
    monkeypatch.setattr(kento, "validate_name", lambda *a, **k: None)
    _stub_get(monkeypatch)
    seen = {}

    def fake_json(inst, *, verbose=False):
        seen["verbose"] = verbose
        return "JSON-INFO"

    monkeypatch.setattr(cli._projection, "instance_to_json", fake_json)
    monkeypatch.setattr(cli._projection, "instance_to_human",
                        lambda *a, **k: pytest.fail("human path used"))
    main(["info", "anything", "--json", "--verbose"])
    assert capsys.readouterr().out.strip() == "JSON-INFO"
    assert seen["verbose"] is True


def test_dispatch_info_scope_maps_to_class(capsys, monkeypatch):
    monkeypatch.setattr(kento, "require_root", lambda: None)
    monkeypatch.setattr(kento, "validate_name", lambda *a, **k: None)
    monkeypatch.setattr(cli._projection, "instance_to_human",
                        lambda *a, **k: "x")

    for argv, expect in (
        (["info", "n"], "base"),
        (["lxc", "info", "n"], "lxc"),
        (["vm", "info", "n"], "vm"),
    ):
        captured = {}
        _stub_get(monkeypatch, captured=captured)
        main(argv)
        assert captured["cls"] == expect
        assert captured["name"] == "n"


def test_dispatch_info_not_found_errors_exit_1(capsys, monkeypatch):
    from kento import InstanceNotFoundError

    monkeypatch.setattr(kento, "require_root", lambda: None)
    monkeypatch.setattr(kento, "validate_name", lambda *a, **k: None)

    def boom(cls, name):
        raise InstanceNotFoundError("no instance named 'ghost'.")

    monkeypatch.setattr(kento.Instance, "get", classmethod(boom))
    with pytest.raises(SystemExit) as exc:
        main(["info", "ghost"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("Error:")
    assert "ghost" in err
