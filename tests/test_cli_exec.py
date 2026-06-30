"""CLI routing tests for the exec command (re-pointed onto SystemContainer.exec)."""

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


def _inst(exit_code=0):
    # The S3-converted SystemContainer.exec returns Result[int]; the CLI
    # .unwrap()s it (behavior-preserving until S7). The mock returns Ok(code).
    from kento import Ok
    inst = MagicMock()
    inst.exec.return_value = Ok(value=exit_code)
    return inst


class TestCliRouting:
    def test_bare_exec_routes_with_dashdash(self):
        from kento_cli import main
        inst = _inst()
        ctx, cap = _patch_lxc(inst)
        with ctx:
            with pytest.raises(SystemExit) as exc:
                main(["exec", "foo", "--", "ls", "-la"])
        assert exc.value.code == 0
        assert cap["name"] == "foo"
        assert cap["scope"] is None
        inst.exec.assert_called_once_with(["ls", "-la"])

    def test_bare_exec_routes_without_dashdash(self):
        from kento_cli import main
        inst = _inst()
        ctx, cap = _patch_lxc(inst)
        with ctx:
            with pytest.raises(SystemExit) as exc:
                main(["exec", "foo", "ls", "-la"])
        assert exc.value.code == 0
        inst.exec.assert_called_once_with(["ls", "-la"])

    def test_lxc_exec_routes(self):
        from kento_cli import main
        inst = _inst()
        ctx, cap = _patch_lxc(inst)
        with ctx:
            with pytest.raises(SystemExit) as exc:
                main(["lxc", "exec", "foo", "--", "ls"])
        assert exc.value.code == 0
        assert cap["scope"] == "lxc"
        inst.exec.assert_called_once_with(["ls"])

    def test_vm_exec_routes_to_resolver(self):
        """`kento vm exec` still routes; _resolve_lxc rejects the VM kind.

        We assert the resolver is asked for scope 'vm' (the rejection of a VM is
        covered by test_vm_exec_rejected below using the real resolver)."""
        from kento_cli import main
        inst = _inst()
        ctx, cap = _patch_lxc(inst)
        with ctx:
            with pytest.raises(SystemExit) as exc:
                main(["vm", "exec", "foo", "--", "ls"])
        assert exc.value.code == 0
        assert cap["scope"] == "vm"
        inst.exec.assert_called_once_with(["ls"])

    def test_exec_remainder_captures_flags(self):
        # Flags after the command name must be captured, not parsed by argparse.
        from kento_cli import main
        inst = _inst()
        ctx, _ = _patch_lxc(inst)
        with ctx:
            with pytest.raises(SystemExit):
                main(["exec", "foo", "--", "journalctl", "-f", "-n", "50"])
        inst.exec.assert_called_once_with(["journalctl", "-f", "-n", "50"])

    def test_cli_propagates_nonzero_exit(self):
        """M13 exec -> int: a non-zero command exit propagates (preserved)."""
        from kento_cli import main
        inst = _inst(exit_code=3)
        ctx, _ = _patch_lxc(inst)
        with ctx:
            with pytest.raises(SystemExit) as exc:
                main(["exec", "foo", "--", "ls"])
        assert exc.value.code == 3

    def test_vm_exec_rejected_with_modeerror(self):
        """A VM (or bare VM name) is rejected with ModeError -> exit 1, using the
        REAL _resolve_lxc against a VirtualMachine handle."""
        from kento_cli import main
        from kento import VirtualMachine
        vm = MagicMock(spec=VirtualMachine)
        with patch("kento_cli._resolve_instance", lambda n, s: vm):
            with pytest.raises(SystemExit) as exc:
                main(["vm", "exec", "foo", "--", "ls"])
        assert exc.value.code == 1
