"""CLI routing tests for the exec command."""

from unittest.mock import patch

import pytest


class TestCliRouting:
    @patch("kento.exec_cmd.exec_cmd", return_value=0)
    def test_bare_exec_routes_with_dashdash(self, mock_exec):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["exec", "foo", "--", "ls", "-la"])
        assert exc.value.code == 0
        mock_exec.assert_called_once_with("foo", ["ls", "-la"], namespace=None)

    @patch("kento.exec_cmd.exec_cmd", return_value=0)
    def test_bare_exec_routes_without_dashdash(self, mock_exec):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["exec", "foo", "ls", "-la"])
        assert exc.value.code == 0
        mock_exec.assert_called_once_with("foo", ["ls", "-la"], namespace=None)

    @patch("kento.exec_cmd.exec_cmd", return_value=0)
    def test_lxc_exec_routes(self, mock_exec):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "exec", "foo", "--", "ls"])
        assert exc.value.code == 0
        mock_exec.assert_called_once_with("foo", ["ls"], namespace="lxc")

    @patch("kento.exec_cmd.exec_cmd", return_value=0)
    def test_vm_exec_routes(self, mock_exec):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["vm", "exec", "foo", "--", "ls"])
        assert exc.value.code == 0
        mock_exec.assert_called_once_with("foo", ["ls"], namespace="vm")

    @patch("kento.exec_cmd.exec_cmd", return_value=0)
    def test_exec_remainder_captures_flags(self, mock_exec):
        # Flags after the command name must be captured, not parsed by argparse.
        from kento_cli import main
        with pytest.raises(SystemExit):
            main(["exec", "foo", "--", "journalctl", "-f", "-n", "50"])
        mock_exec.assert_called_once_with(
            "foo", ["journalctl", "-f", "-n", "50"], namespace=None)

    @patch("kento.exec_cmd.exec_cmd", return_value=3)
    def test_cli_propagates_nonzero_exit(self, mock_exec):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["exec", "foo", "--", "ls"])
        assert exc.value.code == 3
