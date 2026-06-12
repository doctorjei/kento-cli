"""CLI integration tests for validate_name — bad names must be rejected at the CLI layer."""

import pytest


class TestCLIIntegration:
    """CLI entry points must reject bad names before any real work runs."""

    def test_create_rejects_shell_metacharacter_name(self, capsys):
        from kento_cli import main
        with pytest.raises(SystemExit) as excinfo:
            main(["lxc", "create", "debian:13", "--name", "bad;name"])
        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "invalid instance name" in err

    def test_create_rejects_path_traversal_name(self, capsys):
        from kento_cli import main
        with pytest.raises(SystemExit) as excinfo:
            main(["lxc", "create", "debian:13", "--name", "../evil"])
        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "invalid instance name" in err

    def test_start_rejects_slash_in_name(self, capsys):
        from kento_cli import main
        with pytest.raises(SystemExit) as excinfo:
            main(["start", "a/b"])
        # _dispatch_multi catches the inner SystemExit and re-exits 1.
        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "invalid instance name" in err

    def test_info_rejects_double_quote_in_name(self, capsys):
        from kento_cli import main
        with pytest.raises(SystemExit) as excinfo:
            main(["info", 'x"y'])
        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "invalid instance name" in err

    def test_valid_name_does_not_raise_validate_error(self, capsys, monkeypatch):
        """A valid name passes validate_name; later errors are fine, but the
        first error seen must NOT mention 'invalid instance name'."""
        from kento_cli import main

        # Suppress require_root so the path gets to the resolver, which will
        # error out on 'not found' — that's the error we expect, not a
        # validate_name rejection.
        monkeypatch.setattr("os.getuid", lambda: 0)

        # resolve_any will fail with "no instance named" / "instance not found".
        # The CLI catches KentoError and exits 1 with a branded message.
        with pytest.raises(SystemExit):
            main(["info", "valid-name-01"])
        err = capsys.readouterr().err
        assert "invalid instance name" not in err
