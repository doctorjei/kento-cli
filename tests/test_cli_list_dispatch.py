"""The CLI prints whatever list_containers() returns (the library no longer prints)."""
import kento.list as klist

from kento_cli import main


def test_dispatch_list_prints_returned_string(capsys, monkeypatch):
    monkeypatch.setattr(klist, "list_containers",
                        lambda **kw: "FAKE-LISTING-LINE")
    main(["list"])
    assert capsys.readouterr().out.strip() == "FAKE-LISTING-LINE"


def test_dispatch_list_passes_flags(capsys, monkeypatch):
    seen = {}
    def fake(**kw):
        seen.update(kw)
        return "x"
    monkeypatch.setattr(klist, "list_containers", fake)
    main(["list", "--json", "-s"])
    assert seen == {"scope": None, "show_size": True, "as_json": True}
