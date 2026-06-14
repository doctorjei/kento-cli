"""CLI wiring for `kento adopt NAME`.

The library does the work (kento.reconcile.adopt regenerates the missing PVE
config from surviving state); the CLI gates on require_root, calls adopt(name),
and prints a success line from the returned {"name","vmid","mode"} dict. A
KentoError from the library surfaces through the shared _handle path.

The handler imports adopt from kento.reconcile, so these patch that name.
"""
from unittest.mock import patch

import pytest

from kento.errors import StateError

from kento_cli import main


class TestAdopt:

    def test_adopt_calls_library_with_name_and_prints_success(self, capsys):
        result = {"name": "ghost", "vmid": 101, "mode": "pve"}
        with patch("kento.require_root"), \
             patch("kento.reconcile.adopt", return_value=result) as adopt:
            main(["adopt", "ghost"])
        adopt.assert_called_once_with("ghost")
        out = capsys.readouterr().out
        assert "adopted 'ghost' (vmid 101)" in out
        assert "kento start ghost" in out

    def test_adopt_requires_root_before_library_call(self):
        """require_root gates first; adopt never runs if it fails."""
        with patch("kento.require_root", side_effect=SystemExit(1)) as root, \
             patch("kento.reconcile.adopt") as adopt:
            with pytest.raises(SystemExit):
                main(["adopt", "ghost"])
        root.assert_called_once()
        adopt.assert_not_called()

    def test_adopt_library_error_surfaces_via_handle(self, capsys):
        """A KentoError (e.g. not an orphan) becomes 'Error: ...' + exit 1."""
        with patch("kento.require_root"), \
             patch("kento.reconcile.adopt",
                   side_effect=StateError("instance 'ghost' is not an orphan")):
            with pytest.raises(SystemExit) as exc:
                main(["adopt", "ghost"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "Error: instance 'ghost' is not an orphan" in err

    def test_adopt_in_top_help(self, capsys):
        with pytest.raises(SystemExit):
            main(["--help"])
        out = capsys.readouterr().out
        assert "adopt" in out

    def test_adopt_help_shows_command(self, capsys):
        with pytest.raises(SystemExit):
            main(["adopt", "--help"])
        out = capsys.readouterr().out
        assert "adopt" in out
        assert "NAME" in out
