"""CLI attaches handlers to the 'kento' logger: INFO->stdout, WARNING+->stderr,
bare message format (no level prefix), matching the monolith's print behavior."""
import logging

import kento_cli as cli


def test_configure_logging_routes_info_to_stdout(capsys):
    cli._configure_logging()
    logging.getLogger("kento").info("Started: foo")
    out = capsys.readouterr()
    assert out.out.strip() == "Started: foo"
    assert out.err == ""


def test_configure_logging_routes_warning_to_stderr(capsys):
    cli._configure_logging()
    logging.getLogger("kento").warning("pct status timed out")
    out = capsys.readouterr()
    assert out.err.strip() == "pct status timed out"
    assert out.out == ""


def test_configure_logging_is_idempotent(capsys):
    cli._configure_logging()
    cli._configure_logging()
    logging.getLogger("kento").info("once")
    assert capsys.readouterr().out.count("once") == 1
