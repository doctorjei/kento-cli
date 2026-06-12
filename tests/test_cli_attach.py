"""CLI routing tests for the attach/enter command."""

from unittest.mock import patch

import pytest


class TestCliRouting:
    @patch("kento.attach.attach", return_value=0)
    def test_bare_attach_routes(self, mock_attach):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["attach", "foo"])
        assert exc.value.code == 0
        mock_attach.assert_called_once_with("foo", namespace=None)

    @patch("kento.attach.attach", return_value=0)
    def test_bare_enter_routes(self, mock_attach):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["enter", "foo"])
        assert exc.value.code == 0
        mock_attach.assert_called_once_with("foo", namespace=None)

    @patch("kento.attach.attach", return_value=0)
    def test_lxc_attach_routes(self, mock_attach):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "attach", "foo"])
        assert exc.value.code == 0
        mock_attach.assert_called_once_with("foo", namespace="lxc")

    @patch("kento.attach.attach", return_value=0)
    def test_vm_attach_routes(self, mock_attach):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["vm", "attach", "foo"])
        assert exc.value.code == 0
        mock_attach.assert_called_once_with("foo", namespace="vm")

    @patch("kento.attach.attach", return_value=0)
    def test_vm_enter_routes(self, mock_attach):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["vm", "enter", "foo"])
        assert exc.value.code == 0
        mock_attach.assert_called_once_with("foo", namespace="vm")

    @patch("kento.attach.attach", return_value=3)
    def test_cli_propagates_nonzero_exit(self, mock_attach):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["attach", "foo"])
        assert exc.value.code == 3
