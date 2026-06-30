"""Block S7 — the CLI CONSUMES ``Result`` via ``_emit`` (Result-sweep payoff).

Pins the Result -> CLI bridge:

* ``_emit`` on ``Ok``/``Warning``/``Error`` (return value, stderr rendering,
  exit codes 1/2);
* ``--json`` dispatchers gain a top-level ``"warnings"`` array (omitted when
  empty, so the byte-for-byte wire is preserved for clean commands);
* the still-RAISING verbs (setters / ``require_root``) stay on ``_handle``;
* a genuine non-``KentoError`` panic is NOT swallowed by ``_emit``.

Every assertion is mutation-proven (the docstring on each names the mutation
that reddens it).
"""

import json

import pytest

import kento_cli as cli
from kento_cli import (
    _emit,
    _emit_error_code,
    _emit_in_loop,
    _result_warnings_wire,
    main,
)
from kento import Ok, Warning, Error, Condition, ConditionKind, Severity


# --------------------------------------------------------------------------- #
# Helpers — synthesise the Result subclasses the way the core verbs return them.
# --------------------------------------------------------------------------- #


def _ok(value):
    return Ok(value=value)


def _warn(value, message="dropped fragment 'foo'",
          kind=ConditionKind.FRAGMENT_DROPPED, context=None):
    return Warning(
        value=value,
        conditions=(
            Condition(severity=Severity.WARNING, kind=kind,
                      message=message, context=context or {}),
        ),
    )


def _err(message="bad input", kind=ConditionKind.VALIDATION, context=None):
    return Error(
        conditions=(
            Condition(severity=Severity.ERROR, kind=kind,
                      message=message, context=context or {}),
        ),
    )


# --------------------------------------------------------------------------- #
# _emit — Ok.
# --------------------------------------------------------------------------- #


def test_emit_ok_returns_value_no_output(capsys):
    """Ok -> return value, no stderr/stdout. Mutation: making _emit print on Ok
    reddens the empty-stderr assertion."""
    out = _emit(_ok(42))
    assert out == 42
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


# --------------------------------------------------------------------------- #
# _emit — Warning (the new user-visible channel).
# --------------------------------------------------------------------------- #


def test_emit_warning_surfaces_to_stderr_returns_value_exit0(capsys):
    """Warning -> "Warning: <msg>" to STDERR + return value + NO exit. Mutation:
    dropping the warning print leaves stderr empty -> reddens."""
    out = _emit(_warn("the-value", message="dropped fragment 'foo'"))
    assert out == "the-value"  # the value is returned (command proceeds)
    captured = capsys.readouterr()
    assert captured.out == ""  # stdout stays clean (piping/--json)
    assert "Warning: dropped fragment 'foo'\n" == captured.err


def test_emit_warning_one_line_per_condition(capsys):
    """Each WARNING condition prints its own "Warning: <msg>" line. Mutation:
    rendering only the first condition reddens the two-line assertion."""
    result = Warning(
        value="v",
        conditions=(
            Condition(severity=Severity.WARNING,
                      kind=ConditionKind.FRAGMENT_DROPPED, message="first"),
            Condition(severity=Severity.WARNING,
                      kind=ConditionKind.FRAGMENT_DROPPED, message="second"),
        ),
    )
    assert _emit(result) == "v"
    assert capsys.readouterr().err == "Warning: first\nWarning: second\n"


# --------------------------------------------------------------------------- #
# _emit — Error (render + exit).
# --------------------------------------------------------------------------- #


def test_emit_error_renders_and_exits_1(capsys):
    """Error -> "Error: <msg>" to STDERR + exit 1. Mutation: not exiting (or
    exiting 0) reddens; printing to stdout reddens."""
    with pytest.raises(SystemExit) as ei:
        _emit(_err("box already exists", kind=ConditionKind.INSTANCE_EXISTS))
    assert ei.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: box already exists\n"


def test_emit_error_subprocess_missing_tool_exits_2(capsys):
    """A SUBPROCESS_FAILED condition with context["returncode"] is None (tool
    could not launch) -> exit 2. Mutation: mis-picking the code (1) reddens."""
    result = _err("'podman' not found on PATH.",
                  kind=ConditionKind.SUBPROCESS_FAILED,
                  context={"returncode": None, "cmd": ["podman"]})
    with pytest.raises(SystemExit) as ei:
        _emit(result)
    assert ei.value.code == 2
    assert "Error: 'podman' not found on PATH.\n" == capsys.readouterr().err


def test_emit_error_subprocess_with_returncode_exits_1(capsys):
    """A SUBPROCESS_FAILED with a real returncode (the tool ran and failed) ->
    exit 1, NOT 2. Mutation: treating any SUBPROCESS_FAILED as exit 2 reddens."""
    result = _err("pct start failed (exit 3)",
                  kind=ConditionKind.SUBPROCESS_FAILED,
                  context={"returncode": 3, "cmd": ["pct", "start"]})
    with pytest.raises(SystemExit) as ei:
        _emit(result)
    assert ei.value.code == 1


def test_emit_error_subprocess_returncode_absent_exits_1():
    """An ABSENT returncode key is NOT the tool-missing signal -> exit 1 (the
    explicit-None check, matching _error_from which always sets the key)."""
    result = _err("subprocess failed",
                  kind=ConditionKind.SUBPROCESS_FAILED, context={})
    assert _emit_error_code(result) == 1


def test_emit_error_renders_every_error_condition(capsys):
    """Each ERROR condition prints its own "Error: <msg>" line before exit.
    Mutation: rendering only the first reddens the two-line assertion."""
    result = Error(
        conditions=(
            Condition(severity=Severity.ERROR,
                      kind=ConditionKind.VALIDATION, message="e1"),
            Condition(severity=Severity.ERROR,
                      kind=ConditionKind.VALIDATION, message="e2"),
        ),
    )
    with pytest.raises(SystemExit):
        _emit(result)
    assert capsys.readouterr().err == "Error: e1\nError: e2\n"


# --------------------------------------------------------------------------- #
# _emit_error_code — the 1-vs-2 picker, unit-level.
# --------------------------------------------------------------------------- #


def test_emit_error_code_none_returncode_is_2():
    assert _emit_error_code(
        _err("x", kind=ConditionKind.SUBPROCESS_FAILED,
             context={"returncode": None})) == 2


def test_emit_error_code_non_subprocess_is_1():
    assert _emit_error_code(_err("x", kind=ConditionKind.VALIDATION)) == 1


# --------------------------------------------------------------------------- #
# _result_warnings_wire — the --json warnings array projection.
# --------------------------------------------------------------------------- #


def test_warnings_wire_shape():
    """A WARNING condition -> {kind, message, context} with the snake_case kind
    string and a plain-dict context. Mutation: dropping any field reddens."""
    result = _warn("v", message="dropped 'x'",
                   kind=ConditionKind.FRAGMENT_DROPPED,
                   context={"fragment": "x"})
    wire = _result_warnings_wire(result)
    assert wire == [{
        "kind": "fragment_dropped",
        "message": "dropped 'x'",
        "context": {"fragment": "x"},
    }]


def test_warnings_wire_empty_for_ok():
    """Ok / no-warning -> empty list (the caller then omits the key)."""
    assert _result_warnings_wire(_ok("v")) == []


def test_warnings_wire_excludes_non_warning():
    """Only WARNING-severity conditions ride the array (INFO/NOTE notes on an Ok
    are excluded). Mutation: including sub-warning notes reddens."""
    result = Ok(
        value="v",
        conditions=(
            Condition(severity=Severity.INFO,
                      kind=ConditionKind.FRAGMENT_DROPPED, message="note"),
        ),
    )
    assert _result_warnings_wire(result) == []


# --------------------------------------------------------------------------- #
# _emit_in_loop — the non-exiting multi-name variant.
# --------------------------------------------------------------------------- #


def test_emit_in_loop_error_returns_true_no_exit(capsys):
    """_emit_in_loop renders an Error and RETURNS True (no sys.exit) so the
    multi-name accumulator can continue. Mutation: exiting here reddens (the
    loop would abort on the first bad name)."""
    failed = _emit_in_loop(_err("name1 missing",
                                 kind=ConditionKind.INSTANCE_NOT_FOUND))
    assert failed is True
    assert capsys.readouterr().err == "Error: name1 missing\n"


def test_emit_in_loop_ok_returns_false(capsys):
    assert _emit_in_loop(_ok("v")) is False
    assert capsys.readouterr().err == ""


def test_emit_in_loop_warning_surfaces_returns_false(capsys):
    """A Warning in the loop surfaces to stderr but is NOT a failure (False)."""
    assert _emit_in_loop(_warn("v", message="caveat")) is False
    assert capsys.readouterr().err == "Warning: caveat\n"


# --------------------------------------------------------------------------- #
# Still-raising verbs stay on _handle; a genuine panic is NOT swallowed.
# --------------------------------------------------------------------------- #


def test_handle_still_catches_kento_error(capsys):
    """_handle is UNCHANGED for the still-raising verbs (setters/require_root):
    a raised KentoError -> "Error: <msg>" + exit. Mutation: routing these through
    _emit (which expects a Result) would raise AttributeError -> reddens."""
    from kento.errors import StateError
    with pytest.raises(SystemExit) as ei:
        cli._handle(lambda: (_ for _ in ()).throw(StateError("stopped only")))
    assert ei.value.code == 1
    assert "Error: stopped only" in capsys.readouterr().err


def test_emit_does_not_swallow_non_kento_panic():
    """_emit is a Result consumer, NOT an exception catcher. A genuine bug
    (here a raise inside the producing call) propagates as a real traceback — it
    is not silently turned into "Error: ..." + exit. Mutation: wrapping _emit in
    a try/except KentoError would swallow this -> reddens."""
    def boom():
        raise RuntimeError("genuine bug")
    with pytest.raises(RuntimeError, match="genuine bug"):
        _emit(boom())  # boom() raises before _emit ever runs; nothing swallows it


# --------------------------------------------------------------------------- #
# Integration through main() — info --json warnings array (omit-when-empty).
# --------------------------------------------------------------------------- #


def _patch_info_resolve(monkeypatch, result):
    """Make Instance.get return ``result`` and neutralise root/name checks."""
    import kento
    monkeypatch.setattr(kento, "require_root", lambda: None)
    monkeypatch.setattr(kento, "validate_name", lambda *a, **k: None)
    monkeypatch.setattr("kento.Instance.get",
                        staticmethod(lambda name: result))


def test_info_json_clean_omits_warnings_key(capsys, monkeypatch):
    """A clean info --json has NO "warnings" key (byte-for-byte wire preserved).
    Mutation: always emitting "warnings": [] reddens this (and the goldens)."""
    inst = object()
    _patch_info_resolve(monkeypatch, _ok(inst))
    monkeypatch.setattr("kento_cli._projection.instance_to_wire_dict",
                        lambda i, *, verbose=False: {"name": "web"})
    main(["info", "web", "--json"])
    parsed = json.loads(capsys.readouterr().out)
    assert "warnings" not in parsed


def test_info_json_warning_rides_array_and_stderr(capsys, monkeypatch):
    """A warned info --json carries warnings:[{kind,message,context}] in the JSON
    AND surfaces to stderr (both, per Jei). Mutation: dropping the array reddens
    the json assertion; dropping the stderr print reddens the err assertion."""
    inst = object()
    warned = Warning(
        value=inst,
        conditions=(
            Condition(severity=Severity.WARNING,
                      kind=ConditionKind.FRAGMENT_DROPPED,
                      message="dropped 'frag'", context={"fragment": "frag"}),
        ),
    )
    _patch_info_resolve(monkeypatch, warned)
    monkeypatch.setattr("kento_cli._projection.instance_to_wire_dict",
                        lambda i, *, verbose=False: {"name": "web"})
    main(["info", "web", "--json"])
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["warnings"] == [{
        "kind": "fragment_dropped",
        "message": "dropped 'frag'",
        "context": {"fragment": "frag"},
    }]
    assert "Warning: dropped 'frag'\n" == captured.err


def test_diagnose_json_warning_rides_array(capsys, monkeypatch):
    """diagnose --json carries Result WARNING conditions in a top-level warnings
    array (distinct from the scan's findings). Mutation: dropping the array
    reddens. A clean scan omits the key (byte-for-byte wire — pinned elsewhere)."""
    # diag.problems is consulted for the exit code; an empty list -> exit 0.
    class _D:
        problems = []

    cond = Condition(severity=Severity.WARNING,
                     kind=ConditionKind.FRAGMENT_DROPPED,
                     message="scan caveat", context={})
    monkeypatch.setattr("kento.diagnose",
                        lambda name=None: Warning(value=_D(), conditions=(cond,)))
    monkeypatch.setattr("kento.Instance.list",
                        staticmethod(lambda: Ok(value=[])))
    monkeypatch.setattr(
        "kento_cli._projection.diagnosis_to_wire_dict",
        lambda d, *, instances_scanned: {"checks": [], "problem_count": 0,
                                         "instances_scanned": instances_scanned})
    with pytest.raises(SystemExit) as ei:
        main(["diagnose", "--json"])
    assert ei.value.code == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["warnings"] == [
        {"kind": "fragment_dropped", "message": "scan caveat", "context": {}}]


def test_multi_loop_isolates_bad_name_first(capsys, monkeypatch):
    """start over two names where the FIRST resolves to an Error: the bad one is
    rendered AND the LATER good one STILL runs, exit 1 once at the end (per-name
    isolation, NOT abort-on-first-error).

    BAD-NAME-FIRST is load-bearing for the mutation guard (gate C): it makes
    _emit_in_loop's non-exit reddenable. Mutation: replacing _emit_in_loop's
    `return True` with `sys.exit(1)` (or routing resolve through _emit) aborts on
    'ghost' BEFORE 'real' runs -> `started == []` reddens. (A good-FIRST ordering
    would leave the guard hollow — the good name already ran, so an early exit
    still shows started==['real'] + code 1.)"""
    bad = _err("no instance named 'ghost'",
               kind=ConditionKind.INSTANCE_NOT_FOUND)
    started = []

    class _Inst:
        def start(self):
            started.append("real")
            return Ok(value=None)

    # The good Result's value is an instance whose start() returns a Result.
    good = Ok(value=_Inst())
    monkeypatch.setattr("kento.Instance.get",
                        staticmethod(lambda name: good if name == "real" else bad))
    monkeypatch.setattr("kento.validate_name", lambda *a, **k: None)

    with pytest.raises(SystemExit) as ei:
        main(["start", "ghost", "real"])   # BAD FIRST — the guard bites here
    assert ei.value.code == 1              # one failure -> exit 1
    assert started == ["real"]             # the LATER good name STILL ran
    assert "Error: no instance named 'ghost'" in capsys.readouterr().err


def test_info_error_renders_and_exits(capsys, monkeypatch):
    """info on a missing instance -> Error -> "Error: <msg>" + exit 1, no JSON.
    Mutation: not exiting reddens."""
    _patch_info_resolve(
        monkeypatch,
        _err("no instance named 'ghost'",
             kind=ConditionKind.INSTANCE_NOT_FOUND))
    with pytest.raises(SystemExit) as ei:
        main(["info", "ghost", "--json"])
    assert ei.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Error: no instance named 'ghost'" in captured.err
