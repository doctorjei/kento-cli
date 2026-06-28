"""CLI routing tests for the attach/enter command (re-pointed onto Instance.attach)."""

from unittest.mock import MagicMock, patch

import pytest


def _patch_resolve(inst):
    """Patch _resolve_instance to return ``inst`` and capture the (name, scope)."""
    captured = {}

    def fake(name, scope):
        captured["name"] = name
        captured["scope"] = scope
        return inst

    return patch("kento_cli._resolve_instance", fake), captured


class TestCliRouting:
    def test_bare_attach_routes(self):
        from kento_cli import main
        inst = MagicMock()
        ctx, cap = _patch_resolve(inst)
        with ctx:
            main(["attach", "foo"])
        assert cap["name"] == "foo"
        assert cap["scope"] is None
        inst.attach.assert_called_once_with()

    def test_bare_enter_routes(self):
        from kento_cli import main
        inst = MagicMock()
        ctx, cap = _patch_resolve(inst)
        with ctx:
            main(["enter", "foo"])
        assert cap["scope"] is None
        inst.attach.assert_called_once_with()

    def test_lxc_attach_routes(self):
        from kento_cli import main
        inst = MagicMock()
        ctx, cap = _patch_resolve(inst)
        with ctx:
            main(["lxc", "attach", "foo"])
        assert cap["scope"] == "lxc"
        inst.attach.assert_called_once_with()

    def test_vm_attach_routes(self):
        from kento_cli import main
        inst = MagicMock()
        ctx, cap = _patch_resolve(inst)
        with ctx:
            main(["vm", "attach", "foo"])
        assert cap["scope"] == "vm"
        inst.attach.assert_called_once_with()

    def test_vm_enter_routes(self):
        from kento_cli import main
        inst = MagicMock()
        ctx, cap = _patch_resolve(inst)
        with ctx:
            main(["vm", "enter", "foo"])
        assert cap["scope"] == "vm"
        inst.attach.assert_called_once_with()

    def test_clean_detach_exits_zero(self):
        """EXIT-CODE DELTA: typed attach() -> None, so a clean detach exits 0
        regardless of the wrapped tool's exit code (legacy propagated it)."""
        from kento_cli import main
        inst = MagicMock()
        inst.attach.return_value = None
        ctx, _ = _patch_resolve(inst)
        with ctx:
            # No SystemExit(nonzero): the command completes and returns normally.
            main(["attach", "foo"])
        inst.attach.assert_called_once_with()

    def test_attach_failure_propagates_exit_1(self):
        """A genuine failure to attach raises a typed error -> _handle exit 1."""
        from kento_cli import main
        from kento.errors import StateError
        inst = MagicMock()
        inst.attach.side_effect = StateError("no serial socket")
        ctx, _ = _patch_resolve(inst)
        with ctx:
            with pytest.raises(SystemExit) as exc:
                main(["attach", "foo"])
        assert exc.value.code == 1
