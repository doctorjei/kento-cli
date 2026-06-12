"""Black-box: real argv through main(), asserting exit code + stderr, with the
library raising naturally (no monkeypatched verbs)."""
import pytest

from kento_cli import main


def test_bad_name_exits_1_with_error(capsys):
    with pytest.raises(SystemExit) as ei:
        main(["lxc", "create", "bad name with spaces", "--name", "no!!"])
    assert ei.value.code in (1, 2)  # argparse(2) or ValidationError(1) depending on which fires first
    assert "Error" in capsys.readouterr().err or ei.value.code == 2


def test_not_root_info_exits_1(capsys, monkeypatch):
    import os
    if os.getuid() == 0:
        pytest.skip("running as root; require_root would pass")
    with pytest.raises(SystemExit) as ei:
        main(["info", "nonexistent-xyz"])
    assert ei.value.code == 1
    assert capsys.readouterr().err.startswith("Error: ")


def test_version_exits_0(capsys):
    with pytest.raises(SystemExit) as ei:
        main(["--version"])
    assert ei.value.code == 0
    assert "kento" in capsys.readouterr().out
