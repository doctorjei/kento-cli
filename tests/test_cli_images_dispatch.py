"""Dispatch wiring for `kento images` and `kento prune`.

`images` is NOT re-pointed onto Image.list() (M21) — DISCLOSED judgment call:
list_images() reports the kento-MANAGED accounting (guest refs / holds /
in-use), a dataset Image.list() (all podman repo:tags as LayeredImage objects)
does not carry. list_images() returns a STRING (not a dict), so the classes-only
seam rule — which targets legacy --json DICTS — is not violated.

`prune` IS re-pointed (Phase 6): bare prune -> LayeredImage.prune(DANGLING)
(M22) returning a typed ReclaimReport (classes-only seam); --orphans ->
Instance.prune_orphans (M4). This is a CHANGELOG'd behavior delta (the former
kento orphan-HOLD GC is replaced by dangling-image GC).
"""
import kento.images as kimages

import kento_cli as cli


def test_dispatch_images_prints_returned_string(capsys, monkeypatch):
    """`images` still renders the kento-managed accounting table (string seam)."""
    monkeypatch.setattr(kimages, "list_images", lambda **k: "FAKE-IMAGES-TABLE")
    cli.main(["images"])
    assert capsys.readouterr().out.strip() == "FAKE-IMAGES-TABLE"


def test_dispatch_prune_consumes_reclaim_report(capsys, monkeypatch):
    """Bare prune consumes a typed ReclaimReport and renders human text."""
    import kento
    from kento import ReclaimReport
    monkeypatch.setattr(kento, "require_root", lambda: None)
    report = ReclaimReport(dry_run=False, reclaimed=("sha256:aa", "sha256:bb"))
    monkeypatch.setattr(kento.LayeredImage, "prune",
                        classmethod(lambda cls, *, scope: report))
    cli.main(["prune"])
    out = capsys.readouterr().out
    assert "Removed 2 dangling image(s)." in out


def test_dispatch_prune_exits_nonzero_on_failures(capsys, monkeypatch):
    """A ReclaimReport with failures makes the CLI exit 1 after printing."""
    import pytest
    import kento
    from kento import ReclaimReport
    monkeypatch.setattr(kento, "require_root", lambda: None)
    report = ReclaimReport(
        dry_run=False,
        reclaimed=(),
        failed=(("sha256:held", "image is in use"),),
    )
    monkeypatch.setattr(kento.LayeredImage, "prune",
                        classmethod(lambda cls, *, scope: report))
    with pytest.raises(SystemExit) as exc:
        cli.main(["prune"])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "Failed to remove 1 image(s)" in out
    assert "sha256:held: image is in use" in out
