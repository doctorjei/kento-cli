"""CLI integration tests for the info/inspect command."""

import pytest


class TestCliInfo:
    """Test info/inspect command registration in the CLI."""

    def test_info_in_help(self, capsys):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "info" in output
        assert "inspect" in output

    def test_info_help(self, capsys):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["info", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "NAME" in output
        assert "--json" in output
        assert "--verbose" in output

    def test_inspect_help(self, capsys):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["inspect", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "NAME" in output
        assert "--json" in output

    def test_lxc_info_help(self, capsys):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "info", "--help"])
        assert exc.value.code == 0

    def test_vm_info_help(self, capsys):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["vm", "info", "--help"])
        assert exc.value.code == 0

    def test_lxc_inspect_help(self, capsys):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "inspect", "--help"])
        assert exc.value.code == 0

    def test_vm_inspect_help(self, capsys):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["vm", "inspect", "--help"])
        assert exc.value.code == 0

    def test_info_requires_name(self, capsys):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["info"])
        assert exc.value.code != 0

    def test_info_in_lxc_help(self, capsys):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "info" in output
        assert "inspect" in output

    def test_info_in_vm_help(self, capsys):
        from kento_cli import main
        with pytest.raises(SystemExit) as exc:
            main(["vm", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "info" in output
        assert "inspect" in output
