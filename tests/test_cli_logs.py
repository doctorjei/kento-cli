"""CLI routing tests for the logs command."""

from unittest.mock import patch

import pytest


class TestCliRouting:
    @patch("kento.logs.logs", return_value=0)
    def test_bare_logs_routes(self, mock_logs):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["logs", "foo"])
        assert exc.value.code == 0
        mock_logs.assert_called_once_with("foo", [], namespace=None)

    @patch("kento.logs.logs", return_value=0)
    def test_bare_logs_routes_with_flags(self, mock_logs):
        # -f / -n 50 must reach journalctl, not trip argparse.
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["logs", "foo", "-f", "-n", "50"])
        assert exc.value.code == 0
        mock_logs.assert_called_once_with("foo", ["-f", "-n", "50"], namespace=None)

    @patch("kento.logs.logs", return_value=0)
    def test_lxc_logs_routes(self, mock_logs):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "logs", "foo", "-n", "10"])
        assert exc.value.code == 0
        mock_logs.assert_called_once_with("foo", ["-n", "10"], namespace="lxc")

    @patch("kento.logs.logs", return_value=0)
    def test_vm_logs_routes(self, mock_logs):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["vm", "logs", "foo"])
        assert exc.value.code == 0
        mock_logs.assert_called_once_with("foo", [], namespace="vm")

    @patch("kento.logs.logs", return_value=4)
    def test_cli_propagates_nonzero_exit(self, mock_logs):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["logs", "foo"])
        assert exc.value.code == 4
