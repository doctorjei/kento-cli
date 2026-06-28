"""The `list`/`ls` handler re-pointed onto the typed lib + projection.

Block 18 (Phase 6): the handler enumerates `Instance.list()` (scope-narrowed to
SystemContainer/VirtualMachine), drops the JC6 indeterminate-probe rows
(`Status.UNKNOWN`) to preserve today's wire, and prints the Block-17 projection
(`instances_to_json` / `instances_to_human`). The library no longer builds the
strings. These tests assert the WIRING + the JC6 filter; byte-identical output is
pinned by test_projection_golden.py.
"""
from unittest.mock import patch

import kento
from kento import Status
import kento_cli as cli
from kento_cli import main
from kento_cli import _projection  # noqa: F401  (register cli._projection)


class _FakeInst:
    def __init__(self, status):
        self.status = status


def test_dispatch_list_human_prints_projection(capsys, monkeypatch):
    monkeypatch.setattr(kento.Instance, "list", classmethod(lambda cls: []))
    monkeypatch.setattr(cli._projection, "instances_to_human",
                        lambda insts, *, show_size=False: "LISTING-TABLE")
    main(["list"])
    assert capsys.readouterr().out.strip() == "LISTING-TABLE"


def test_dispatch_list_json_branch(capsys, monkeypatch):
    monkeypatch.setattr(kento.Instance, "list", classmethod(lambda cls: []))
    monkeypatch.setattr(cli._projection, "instances_to_json",
                        lambda insts, *, show_size=False: "LISTING-JSON")
    main(["list", "--json"])
    assert capsys.readouterr().out.strip() == "LISTING-JSON"


def test_dispatch_list_passes_show_size(capsys, monkeypatch):
    seen = {}

    def fake(insts, *, show_size=False):
        seen["show_size"] = show_size
        return "x"

    monkeypatch.setattr(kento.Instance, "list", classmethod(lambda cls: []))
    monkeypatch.setattr(cli._projection, "instances_to_human", fake)
    main(["list", "-s"])
    assert seen["show_size"] is True


def test_dispatch_list_jc6_filters_unknown(capsys, monkeypatch):
    """JC6: an indeterminate-probe instance (Status.UNKNOWN) is dropped so the
    projected wire matches today's list.py (which SKIPS that row). Healthy
    statuses pass through untouched."""
    running = _FakeInst(Status.RUNNING)
    unknown = _FakeInst(Status.UNKNOWN)
    orphan = _FakeInst(Status.ORPHAN)
    monkeypatch.setattr(kento.Instance, "list",
                        classmethod(lambda cls: [running, unknown, orphan]))
    seen = {}

    def fake(insts, *, show_size=False):
        seen["insts"] = list(insts)
        return "x"

    monkeypatch.setattr(cli._projection, "instances_to_human", fake)
    main(["list"])
    # UNKNOWN filtered out; RUNNING + ORPHAN (a status list.py DOES emit) kept.
    assert seen["insts"] == [running, orphan]


def test_dispatch_list_scope_maps_to_class(capsys, monkeypatch):
    monkeypatch.setattr(cli._projection, "instances_to_human",
                        lambda insts, *, show_size=False: "x")
    for argv, cls in (
        (["list"], kento.Instance),
        (["lxc", "list"], kento.SystemContainer),
        (["vm", "list"], kento.VirtualMachine),
    ):
        seen = {"cls": None}

        def fake_list(c, _seen=seen):
            _seen["cls"] = c
            return []

        monkeypatch.setattr(cls, "list", classmethod(fake_list))
        main(argv)
        assert seen["cls"] is cls
