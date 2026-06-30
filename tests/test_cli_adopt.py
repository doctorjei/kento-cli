"""CLI wiring for `kento adopt NAME` (Phase 6 re-point).

Re-pointed onto Instance.adopt (M3): the library heals the orphan (regenerates
the missing PVE config from surviving state) and returns a typed Instance
handle. CLASSES-ONLY: the CLI gates on require_root, calls Instance.adopt(name),
and formats the success line from the handle's public properties — name and the
PVE vmid (platform_profile.mid). A KentoError from the library surfaces through
the shared _handle path.
"""
from unittest.mock import MagicMock, patch

import pytest

from kento import Condition, ConditionKind, Error, Ok, Severity

from kento_cli import main


def _fake_handle(name="ghost", mid=101):
    inst = MagicMock()
    inst.name = name
    inst.platform_profile.mid = mid
    return inst


class TestAdopt:

    def test_adopt_calls_library_with_name_and_prints_success(self, capsys):
        handle = _fake_handle()
        # S6 (Result sweep): Instance.adopt returns a Result; the CLI .unwrap()s.
        with patch("kento.require_root"), \
             patch("kento.Instance.adopt",
                   return_value=Ok(value=handle)) as adopt:
            main(["adopt", "ghost"])
        adopt.assert_called_once_with("ghost")
        out = capsys.readouterr().out
        assert "adopted 'ghost' (vmid 101)" in out
        assert "kento start ghost" in out

    def test_adopt_requires_root_before_library_call(self):
        """require_root gates first; adopt never runs if it fails."""
        with patch("kento.require_root", side_effect=SystemExit(1)) as root, \
             patch("kento.Instance.adopt") as adopt:
            with pytest.raises(SystemExit):
                main(["adopt", "ghost"])
        root.assert_called_once()
        adopt.assert_not_called()

    def test_adopt_library_error_surfaces_via_handle(self, capsys):
        """S6: a failure is Error(INVALID_STATE); the CLI .unwrap()s it ->
        ResultError (a KentoError) -> _handle -> 'Error: ...' + exit 1 (message
        preserved, byte-identical wire)."""
        err_result = Error(conditions=(Condition(
            severity=Severity.ERROR,
            kind=ConditionKind.INVALID_STATE,
            message="instance 'ghost' is not an orphan",
            context={}),))
        with patch("kento.require_root"), \
             patch("kento.Instance.adopt", return_value=err_result):
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
