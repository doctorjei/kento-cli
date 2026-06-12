"""The CLI is the only place that turns KentoError into an exit code + message."""
import logging

import pytest

import kento_cli as cli
from kento.errors import (
    KentoError, ValidationError, InstanceNotFoundError, InstanceExistsError,
    ImageNotFoundError, ModeError, StateError, SubprocessError,
)


@pytest.mark.parametrize("exc", [
    ValidationError("bad name"),
    InstanceNotFoundError("no such instance"),
    InstanceExistsError("already exists"),
    ImageNotFoundError("no image"),
    ModeError("wrong mode"),
    StateError("not running"),
    SubprocessError("failed to start (exit 1)", cmd=["pct", "start"], returncode=1),
])
def test_kento_error_exits_1_with_prefix(exc, capsys):
    with pytest.raises(SystemExit) as ei:
        cli._handle(lambda: (_ for _ in ()).throw(exc))
    assert ei.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("Error: ")
    assert str(exc) in err


def test_missing_tool_subprocess_error_exits_2(capsys):
    exc = SubprocessError("'pct' not found on PATH.", cmd=["pct"])  # returncode None
    with pytest.raises(SystemExit) as ei:
        cli._handle(lambda: (_ for _ in ()).throw(exc))
    assert ei.value.code == 2
    assert "Error: " in capsys.readouterr().err


def test_success_returns_none_no_exit():
    assert cli._handle(lambda: 0) == 0
    assert cli._handle(lambda: None) is None


def test_exit_code_for_each_type():
    assert cli._exit_code(ValidationError("x")) == 1
    assert cli._exit_code(SubprocessError("missing", cmd=["x"])) == 2          # returncode None
    assert cli._exit_code(SubprocessError("nonzero", cmd=["x"], returncode=3)) == 1
