"""CLI wiring for `kento prune --orphans [--yes]`.

Bare `kento prune` is unchanged (images/holds only, exercised in test_cli.py's
TestPruneCommand). `--orphans` ADDS a separately sectioned orphan-reaping pass:
the library does the work (kento.reconcile.reap_orphans / format_reap); the CLI
routes args (reap=args.yes — dry-run unless --yes) and prints the section after
the existing images/holds output.

The handler imports reap_orphans/format_reap from kento.reconcile, so these
patch that name. images.prune is mocked so these tests stay hermetic and assert
ONLY the orphan wiring.
"""
from unittest.mock import patch

import pytest

from kento_cli import main


def _orphan_results():
    return [{"name": "ghost", "vmid": 101, "mode": "pve",
             "reaped": False, "error": None}]


class TestPruneOrphans:

    def test_bare_prune_does_not_touch_orphans(self):
        """kento prune (no --orphans) must NOT call reap_orphans at all."""
        with patch("kento.require_root"), \
             patch("kento.images.prune", return_value="IMAGES-OUT"), \
             patch("kento.reconcile.reap_orphans") as reap:
            main(["prune"])
        reap.assert_not_called()

    def test_bare_prune_yes_does_not_touch_orphans(self):
        with patch("kento.require_root"), \
             patch("kento.images.prune", return_value="IMAGES-OUT"), \
             patch("kento.reconcile.reap_orphans") as reap:
            main(["prune", "--yes"])
        reap.assert_not_called()

    def test_orphans_dry_run_lists_but_does_not_reap(self, capsys):
        """prune --orphans (no --yes) calls reap_orphans(reap=False)."""
        with patch("kento.require_root"), \
             patch("kento.images.prune", return_value="IMAGES-OUT"), \
             patch("kento.reconcile.reap_orphans",
                   return_value=_orphan_results()) as reap, \
             patch("kento.reconcile.format_reap",
                   return_value="ORPHANS-DRY") as fmt:
            main(["prune", "--orphans"])
        reap.assert_called_once_with(reap=False)
        fmt.assert_called_once_with(_orphan_results(), reaped=False)
        out = capsys.readouterr().out
        # Existing images/holds output is still printed, then the orphan section.
        assert "IMAGES-OUT" in out
        assert "ORPHANS-DRY" in out
        assert out.index("IMAGES-OUT") < out.index("ORPHANS-DRY")

    def test_orphans_yes_triggers_reap(self, capsys):
        """prune --orphans --yes calls reap_orphans(reap=True)."""
        with patch("kento.require_root"), \
             patch("kento.images.prune", return_value="IMAGES-OUT"), \
             patch("kento.reconcile.reap_orphans",
                   return_value=_orphan_results()) as reap, \
             patch("kento.reconcile.format_reap",
                   return_value="ORPHANS-REAPED") as fmt:
            main(["prune", "--orphans", "--yes"])
        reap.assert_called_once_with(reap=True)
        fmt.assert_called_once_with(_orphan_results(), reaped=True)
        out = capsys.readouterr().out
        assert "IMAGES-OUT" in out
        assert "ORPHANS-REAPED" in out

    def test_orphans_requires_root_before_reaping(self):
        """--orphans still gates on require_root; reap never runs if it fails."""
        with patch("kento.require_root", side_effect=SystemExit(1)) as root, \
             patch("kento.images.prune"), \
             patch("kento.reconcile.reap_orphans") as reap:
            with pytest.raises(SystemExit):
                main(["prune", "--orphans"])
        root.assert_called_once()
        reap.assert_not_called()

    def test_orphans_flag_in_prune_help(self, capsys):
        with pytest.raises(SystemExit):
            main(["prune", "--help"])
        out = capsys.readouterr().out
        assert "--orphans" in out
