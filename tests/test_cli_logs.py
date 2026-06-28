"""CLI routing tests for the logs command (re-pointed onto SystemContainer.logs).

Jei-ruled M14 refinement: the arbitrary journalctl pass-through is PRESERVED — the
REMAINDER is forwarded verbatim as the typed method's ``args``.
"""

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
        inst.logs.assert_called_once_with(args=[])
        out = capsys.readouterr().out
        assert "line one" in out and "line two" in out

    def test_bare_logs_passes_through_flags(self):
        # -f / -n 50 are forwarded verbatim to journalctl (pass-through).
        from kento_cli import main
        inst = _inst()
        ctx, _ = _patch_lxc(inst)
        with ctx:
            main(["logs", "foo", "-f", "-n", "50"])
        inst.logs.assert_called_once_with(args=["-f", "-n", "50"])

    def test_lxc_logs_lines(self):
        from kento_cli import main
        inst = _inst()
        ctx, cap = _patch_lxc(inst)
        with ctx:
            main(["lxc", "logs", "foo", "-n", "10"])
        assert cap["scope"] == "lxc"
        inst.logs.assert_called_once_with(args=["-n", "10"])

    def test_arbitrary_journalctl_args_pass_through(self):
        # The Jei-ruled refinement: arbitrary journalctl flags reach journalctl.
        from kento_cli import main
        inst = _inst()
        ctx, _ = _patch_lxc(inst)
        with ctx:
            main(["logs", "foo", "--since", "yesterday", "-u", "sshd"])
        inst.logs.assert_called_once_with(
            args=["--since", "yesterday", "-u", "sshd"])

    def test_leading_dashdash_stripped(self):
        from kento_cli import main
        inst = _inst()
        ctx, _ = _patch_lxc(inst)
        with ctx:
            main(["logs", "foo", "--", "-f", "--since", "10:00"])
        inst.logs.assert_called_once_with(args=["-f", "--since", "10:00"])

    def test_vm_logs_rejected_with_modeerror(self):
        """A VM is rejected with ModeError -> exit 1 (real _resolve_lxc)."""
        from kento_cli import main
        from kento import VirtualMachine
        vm = MagicMock(spec=VirtualMachine)
        with patch("kento_cli._resolve_instance", lambda n, s: vm):
            with pytest.raises(SystemExit) as exc:
                main(["vm", "logs", "foo"])
        assert exc.value.code == 1
