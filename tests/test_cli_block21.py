"""Block 21 (Phase 6 FINAL) — typed re-point of images/pull/prune/adopt.

Focused tests for the CLASSES-ONLY seam: the CLI consumes typed objects
(OciImage handles, ReclaimReport, Instance handles) and formats human text
at the edge. The ReclaimReport formatters are exercised directly here.
"""
from unittest.mock import MagicMock, patch

import pytest

from kento import ReclaimReport

import kento_cli as cli
from kento_cli import _format_image_prune, _format_orphan_prune


# --------------------------------------------------------------------------- #
# ReclaimReport formatters (pure — no I/O, classes in / strings out).
# --------------------------------------------------------------------------- #

class TestImagePruneFormatter:

    def test_none_reclaimed(self):
        out = _format_image_prune(ReclaimReport(dry_run=False))
        assert out == "Removed 0 dangling image(s)."

    def test_some_reclaimed(self):
        report = ReclaimReport(dry_run=False, reclaimed=("a", "b", "c"))
        assert _format_image_prune(report) == "Removed 3 dangling image(s)."

    def test_failures_surfaced(self):
        report = ReclaimReport(
            dry_run=False, reclaimed=("a",),
            failed=(("b", "in use"), ("c", "held")))
        out = _format_image_prune(report)
        assert "Removed 1 dangling image(s)." in out
        assert "Failed to remove 2 image(s)" in out
        assert "  b: in use" in out
        assert "  c: held" in out


class TestOrphanPruneFormatter:

    def test_dry_run_none(self):
        out = _format_orphan_prune(ReclaimReport(dry_run=True))
        assert out == "Orphans: none found."

    def test_dry_run_lists_candidates(self):
        report = ReclaimReport(dry_run=True, reclaimed=("g1", "g2"))
        out = _format_orphan_prune(report)
        assert "Dry run — nothing destroyed. 2 orphaned" in out
        assert "    g1" in out
        assert "    g2" in out
        assert "kento prune --orphans --yes" in out

    def test_reaped_summary(self):
        report = ReclaimReport(dry_run=False, reclaimed=("g1", "g2"))
        out = _format_orphan_prune(report)
        assert "reaped g1" in out
        assert "reaped g2" in out
        assert "Destroyed 2 orphan(s)." in out

    def test_reaped_with_failures(self):
        report = ReclaimReport(
            dry_run=False, reclaimed=("g1",),
            failed=(("g2", "boom"),))
        out = _format_orphan_prune(report)
        assert "reaped g1" in out
        assert "FAILED g2: boom" in out
        assert "Destroyed 1 orphan(s), 1 failed." in out

    def test_reaped_none_found(self):
        out = _format_orphan_prune(ReclaimReport(dry_run=False))
        assert out == "Orphans: none found."


# --------------------------------------------------------------------------- #
# Handler integration — classes-only seam.
# --------------------------------------------------------------------------- #

class TestImagesInUse:
    """`images` re-pointed (SD3, JC1) onto the typed kento.ImageRecord.list();
    --in-use filters the typed list CLI-side (record.in_use). No library string
    crosses the seam — the former list_images() was removed."""

    def _rec(self, *, encoded, guests=()):
        from kento import Digest, ImageRecord
        return ImageRecord(
            id=Digest(algorithm="sha256", encoded=encoded), guests=tuple(guests))

    def test_in_use_filters_orphaned_cli_side(self, capsys):
        import kento
        records = [
            self._rec(encoded="a" * 64, guests=["box"]),  # in-use
            self._rec(encoded="b" * 64),                   # orphaned
        ]
        with patch.object(kento.ImageRecord, "list",
                          classmethod(lambda cls: list(records))):
            cli.main(["images", "--in-use"])
        out = capsys.readouterr().out
        assert "aaaaaaaaaaaa" in out
        assert "bbbbbbbbbbbb" not in out

    def test_default_shows_all(self, capsys):
        import kento
        records = [
            self._rec(encoded="a" * 64, guests=["box"]),
            self._rec(encoded="b" * 64),
        ]
        with patch.object(kento.ImageRecord, "list",
                          classmethod(lambda cls: list(records))):
            cli.main(["images"])
        out = capsys.readouterr().out
        assert "aaaaaaaaaaaa" in out
        assert "bbbbbbbbbbbb" in out


class TestPullClassesOnly:

    def test_pull_consumes_handle_renders_source(self, capsys):
        handle = MagicMock()
        handle.source.render.return_value = "registry/x:1"
        with patch("kento.require_root"), \
             patch("kento.OciImage.pull", return_value=handle) as pull:
            cli.main(["pull", "x:1"])
        pull.assert_called_once_with("x:1")
        assert "Pulled registry/x:1" in capsys.readouterr().out


class TestPruneBothSectionsAndExit:

    def test_both_sections_print_then_exit_1_on_any_failure(self, capsys):
        """Image failure + clean orphans -> both print, exit 1."""
        img = ReclaimReport(dry_run=False, reclaimed=(),
                            failed=(("x", "held"),))
        orph = ReclaimReport(dry_run=True, reclaimed=("g",))
        with patch("kento.require_root"), \
             patch("kento.OciImage.prune", return_value=img), \
             patch("kento.Instance.prune_orphans", return_value=orph):
            with pytest.raises(SystemExit) as exc:
                cli.main(["prune", "--orphans"])
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "Failed to remove 1 image(s)" in out
        assert "WOULD be destroyed" in out

    def test_clean_both_exits_0(self, capsys):
        img = ReclaimReport(dry_run=False, reclaimed=("a",))
        orph = ReclaimReport(dry_run=True)
        with patch("kento.require_root"), \
             patch("kento.OciImage.prune", return_value=img), \
             patch("kento.Instance.prune_orphans", return_value=orph):
            # No SystemExit on a clean run.
            cli.main(["prune", "--orphans"])
        out = capsys.readouterr().out
        assert "Removed 1 dangling image(s)." in out
        assert "Orphans: none found." in out
