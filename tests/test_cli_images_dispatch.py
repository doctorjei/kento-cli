"""Dispatch wiring for `kento images` and `kento prune`.

`images` IS re-pointed (SD3, JC1) onto the typed ledger
`kento.ImageRecord.list()` — the LAST classes-only seam for images. The
library no longer renders the table as a string (list_images() was removed);
the CLI formats the typed records (images_to_human). NO library string crosses
the seam and NO --json (D2). The --in-use flag is preserved by filtering the
typed list CLI-side (record.in_use).

`prune` IS re-pointed (Phase 6): bare prune -> OciImage.prune(DANGLING)
(M22) returning a typed ReclaimReport (classes-only seam); --orphans ->
Instance.prune_orphans (M4). This is a CHANGELOG'd behavior delta (the former
kento orphan-HOLD GC is replaced by dangling-image GC).
"""
import kento_cli as cli


def _rec(*, encoded, refs=(), guests=(), holds=()):
    """Build a kento.ImageRecord (typed) for the dispatch tests."""
    from kento import Digest, ImageRecord, OciReference

    return ImageRecord(
        id=Digest(algorithm="sha256", encoded=encoded),
        refs=tuple(OciReference.parse(r) for r in refs),
        guests=tuple(guests),
        holds=tuple(holds),
    )


def test_dispatch_images_uses_typed_ledger_not_string(capsys, monkeypatch):
    """`images` consumes kento.ImageRecord.list() — typed records, no library
    string crosses the seam (the removed list_images())."""
    import kento

    records = [_rec(encoded="a" * 64, refs=["imagea:latest"], guests=["box"])]
    monkeypatch.setattr(kento.ImageRecord, "list",
                        classmethod(lambda cls: list(records)))
    cli.main(["images"])
    out = capsys.readouterr().out
    # The CLI formats the typed record into the table: the ref, the short id,
    # the guest, the hold flag, and the status all render.
    assert "imagea:latest" in out
    assert "aaaaaaaaaaaa" in out  # short content id (12 hex)
    assert "box" in out
    assert "in-use" in out
    # The legacy string surface is gone from the library.
    import kento.images as kimages
    assert not hasattr(kimages, "list_images")


def test_dispatch_images_in_use_filters_orphaned(capsys, monkeypatch):
    """--in-use filters the typed list CLI-side (record.in_use)."""
    import kento

    records = [
        _rec(encoded="a" * 64, refs=["imagea:latest"], guests=["box"]),
        _rec(encoded="b" * 64, refs=["imageb:latest"]),  # orphaned, no guest
    ]
    monkeypatch.setattr(kento.ImageRecord, "list",
                        classmethod(lambda cls: list(records)))
    cli.main(["images", "--in-use"])
    out = capsys.readouterr().out
    assert "imagea:latest" in out
    assert "imageb:latest" not in out


def test_dispatch_images_empty(capsys, monkeypatch):
    """No managed images => the legacy 'No kento-managed images.' line."""
    import kento

    monkeypatch.setattr(kento.ImageRecord, "list", classmethod(lambda cls: []))
    cli.main(["images"])
    assert "No kento-managed images." in capsys.readouterr().out


def test_dispatch_prune_consumes_reclaim_report(capsys, monkeypatch):
    """Bare prune consumes a typed ReclaimReport and renders human text."""
    import kento
    from kento import ReclaimReport
    monkeypatch.setattr(kento, "require_root", lambda: None)
    report = ReclaimReport(dry_run=False, reclaimed=("sha256:aa", "sha256:bb"))
    monkeypatch.setattr(kento.OciImage, "prune",
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
    monkeypatch.setattr(kento.OciImage, "prune",
                        classmethod(lambda cls, *, scope: report))
    with pytest.raises(SystemExit) as exc:
        cli.main(["prune"])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "Failed to remove 1 image(s)" in out
    assert "sha256:held: image is in use" in out
