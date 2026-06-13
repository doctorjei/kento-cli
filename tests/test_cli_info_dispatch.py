"""The CLI prints whatever info() returns (the library no longer prints)."""
import kento
import kento.info as kinfo

from kento_cli import main


def test_dispatch_info_prints_returned_string(capsys, monkeypatch):
    monkeypatch.setattr(kento, "require_root", lambda: None)
    monkeypatch.setattr(kento, "validate_name", lambda *a, **k: None)
    monkeypatch.setattr(kento, "resolve_any", lambda *a, **k: ("/fake/dir", "lxc"))
    monkeypatch.setattr(kinfo, "info", lambda *a, **k: "FAKE-INFO-BLOCK")
    main(["info", "anything"])
    assert capsys.readouterr().out.strip() == "FAKE-INFO-BLOCK"
