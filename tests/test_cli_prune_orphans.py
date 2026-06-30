"""CLI wiring for `kento prune --orphans [--yes]` (Phase 6 re-point).

Bare `kento prune` reclaims podman DANGLING images via OciImage.prune (M22).
`--orphans` ADDS a separately sectioned orphan-reaping pass routed onto
Instance.prune_orphans (M4): reap=args.yes (dry-run unless --yes). Both ops
return a typed ReclaimReport (classes-only seam — no dict crosses); the CLI
formats the human text at the edge.

OciImage.prune is mocked so these tests stay hermetic and assert ONLY the
orphan wiring.
"""
from unittest.mock import patch

import pytest

from kento import ReclaimReport

from kento_cli import main


def _clean_image_report():
    return ReclaimReport(dry_run=False)


def _orphan_report(*, dry_run):
    return ReclaimReport(dry_run=dry_run, reclaimed=("ghost",))


class TestPruneOrphans:

    def test_bare_prune_does_not_touch_orphans(self):
        """kento prune (no --orphans) must NOT call prune_orphans at all."""
        with patch("kento.require_root"), \
             patch("kento.OciImage.prune",
                   return_value=__import__("kento").Ok(
                       value=_clean_image_report())), \
             patch("kento.Instance.prune_orphans") as reap:
            main(["prune"])
        reap.assert_not_called()

    def test_bare_prune_yes_does_not_touch_orphans(self):
        with patch("kento.require_root"), \
             patch("kento.OciImage.prune",
                   return_value=__import__("kento").Ok(
                       value=_clean_image_report())), \
             patch("kento.Instance.prune_orphans") as reap:
            main(["prune", "--yes"])
        reap.assert_not_called()

    def test_orphans_dry_run_lists_but_does_not_reap(self, capsys):
        """prune --orphans (no --yes) calls prune_orphans(reap=False)."""
        with patch("kento.require_root"), \
             patch("kento.OciImage.prune",
                   return_value=__import__("kento").Ok(
                       value=_clean_image_report())), \
             patch("kento.Instance.prune_orphans",
                   return_value=_orphan_report(dry_run=True)) as reap:
            main(["prune", "--orphans"])
        reap.assert_called_once_with(reap=False)
        out = capsys.readouterr().out
        # The dangling-image section prints first, then the orphan section.
        assert "dangling image(s)" in out
        assert "WOULD be destroyed" in out
        assert out.index("dangling image(s)") < out.index("WOULD be destroyed")

    def test_orphans_yes_triggers_reap(self, capsys):
        """prune --orphans --yes calls prune_orphans(reap=True)."""
        with patch("kento.require_root"), \
             patch("kento.OciImage.prune",
                   return_value=__import__("kento").Ok(
                       value=_clean_image_report())), \
             patch("kento.Instance.prune_orphans",
                   return_value=_orphan_report(dry_run=False)) as reap:
            main(["prune", "--orphans", "--yes"])
        reap.assert_called_once_with(reap=True)
        out = capsys.readouterr().out
        assert "reaped ghost" in out

    def test_orphans_failure_exits_nonzero(self, capsys):
        """A failed reap (ReclaimReport.failed) makes the CLI exit 1."""
        report = ReclaimReport(
            dry_run=False, reclaimed=(),
            failed=(("ghost", "destroy refused"),))
        with patch("kento.require_root"), \
             patch("kento.OciImage.prune",
                   return_value=__import__("kento").Ok(
                       value=_clean_image_report())), \
             patch("kento.Instance.prune_orphans", return_value=report):
            with pytest.raises(SystemExit) as exc:
                main(["prune", "--orphans", "--yes"])
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "FAILED ghost: destroy refused" in out

    def test_orphans_requires_root_before_reaping(self):
        """--orphans still gates on require_root; reap never runs if it fails."""
        with patch("kento.require_root", side_effect=SystemExit(1)) as root, \
             patch("kento.OciImage.prune"), \
             patch("kento.Instance.prune_orphans") as reap:
            with pytest.raises(SystemExit):
                main(["prune", "--orphans"])
        root.assert_called_once()
        reap.assert_not_called()

    def test_orphans_flag_in_prune_help(self, capsys):
        with pytest.raises(SystemExit):
            main(["prune", "--help"])
        out = capsys.readouterr().out
        assert "--orphans" in out
