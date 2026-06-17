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
    # prune() now returns (summary_text, failed_count); the handler prints
    # the text and exits 0 when there are no failures.
    monkeypatch.setattr(kimages, "prune", lambda **k: ("FAKE-PRUNE-PLAN", 0))
    cli.main(["prune"])
    assert capsys.readouterr().out.strip() == "FAKE-PRUNE-PLAN"


def test_dispatch_prune_exits_nonzero_on_failures(capsys, monkeypatch):
    import pytest
    import kento
    monkeypatch.setattr(kento, "require_root", lambda: None)
    # A non-zero failure count must make the CLI exit non-zero, after the
    # summary text has printed.
    monkeypatch.setattr(kimages, "prune", lambda **k: ("FAKE-PRUNE-FAIL", 2))
    with pytest.raises(SystemExit) as exc:
        cli.main(["prune"])
    assert exc.value.code == 1
    assert capsys.readouterr().out.strip() == "FAKE-PRUNE-FAIL"
