"""The CLI prints whatever images list_images()/prune() return."""
import kento.images as kimages

import kento_cli as cli


def test_dispatch_images_prints_returned_string(capsys, monkeypatch):
    monkeypatch.setattr(kimages, "list_images", lambda **k: "FAKE-IMAGES-TABLE")
    cli.main(["images"])
    assert capsys.readouterr().out.strip() == "FAKE-IMAGES-TABLE"


def test_dispatch_prune_prints_returned_string(capsys, monkeypatch):
    import kento
    monkeypatch.setattr(kento, "require_root", lambda: None)
    monkeypatch.setattr(kimages, "prune", lambda **k: "FAKE-PRUNE-PLAN")
    cli.main(["prune"])
    assert capsys.readouterr().out.strip() == "FAKE-PRUNE-PLAN"
