"""CLI routing tests for the logs command (re-pointed onto SystemContainer.logs)."""

from unittest.mock import MagicMock, patch

import pytest


def _patch_lxc(inst):
    """Patch _resolve_lxc to return ``inst`` and capture (name, scope, what)."""
    captured = {}

    def fake(name, scope, *, what):
        captured["name"] = name
        captured["scope"] = scope
        captured["what"] = what
        return inst

    return patch("kento_cli._resolve_lxc", fake), captured


def _inst(lines=()):
    inst = MagicMock()
    inst.logs.return_value = iter(lines)
    return inst


class TestCliRouting:
    def test_bare_logs_routes(self, capsys):
        from kento_cli import main
        inst = _inst(["line one", "line two"])
        ctx, cap = _patch_lxc(inst)
        with ctx:
            main(["logs", "foo"])
        assert cap["name"] == "foo"
        assert cap["scope"] is None
        inst.logs.assert_called_once_with(follow=False, lines=None)
        out = capsys.readouterr().out
        assert "line one" in out and "line two" in out

    def test_bare_logs_follow_and_lines(self):
        # -f / -n 50 are parsed into the typed follow/lines kwargs.
        from kento_cli import main
        inst = _inst()
        ctx, _ = _patch_lxc(inst)
        with ctx:
            main(["logs", "foo", "-f", "-n", "50"])
        inst.logs.assert_called_once_with(follow=True, lines=50)

    def test_lxc_logs_lines(self):
        from kento_cli import main
        inst = _inst()
        ctx, cap = _patch_lxc(inst)
        with ctx:
            main(["lxc", "logs", "foo", "-n", "10"])
        assert cap["scope"] == "lxc"
        inst.logs.assert_called_once_with(follow=False, lines=10)

    def test_logs_long_flags(self):
        from kento_cli import main
        inst = _inst()
        ctx, _ = _patch_lxc(inst)
        with ctx:
            main(["logs", "foo", "--follow", "--lines", "5"])
        inst.logs.assert_called_once_with(follow=True, lines=5)

    def test_logs_lines_equals_form(self):
        from kento_cli import main
        inst = _inst()
        ctx, _ = _patch_lxc(inst)
        with ctx:
            main(["logs", "foo", "--lines=7"])
        inst.logs.assert_called_once_with(follow=False, lines=7)

    def test_logs_n_glued_form(self):
        from kento_cli import main
        inst = _inst()
        ctx, _ = _patch_lxc(inst)
        with ctx:
            main(["logs", "foo", "-n20"])
        inst.logs.assert_called_once_with(follow=False, lines=20)

    def test_unsupported_arg_rejected(self, capsys):
        """DELTA: arbitrary journalctl args are no longer forwarded (exit 1)."""
        from kento_cli import main
        inst = _inst()
        ctx, _ = _patch_lxc(inst)
        with ctx:
            with pytest.raises(SystemExit) as exc:
                main(["logs", "foo", "--since", "yesterday"])
        assert exc.value.code == 1
        assert "unsupported logs argument" in capsys.readouterr().err
        inst.logs.assert_not_called()

    def test_bad_line_count_rejected(self):
        from kento_cli import main
        inst = _inst()
        ctx, _ = _patch_lxc(inst)
        with ctx:
            with pytest.raises(SystemExit) as exc:
                main(["logs", "foo", "-n", "abc"])
        assert exc.value.code == 1
        inst.logs.assert_not_called()

    def test_negative_line_count_rejected(self):
        from kento_cli import main
        inst = _inst()
        ctx, _ = _patch_lxc(inst)
        with ctx:
            with pytest.raises(SystemExit) as exc:
                main(["logs", "foo", "-n", "-3"])
        assert exc.value.code == 1
        inst.logs.assert_not_called()

    def test_vm_logs_rejected_with_modeerror(self):
        """A VM is rejected with ModeError -> exit 1 (real _resolve_lxc)."""
        from kento_cli import main
        from kento import VirtualMachine
        vm = MagicMock(spec=VirtualMachine)
        with patch("kento_cli._resolve_instance", lambda n, s: vm):
            with pytest.raises(SystemExit) as exc:
                main(["vm", "logs", "foo"])
        assert exc.value.code == 1
