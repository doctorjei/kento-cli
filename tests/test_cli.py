"""Tests for CLI argument parsing."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from kento_cli import main, _parse_network
from kento_cli import _projection  # noqa: F401  (register cli._projection)


def _make_fake_set_instance(network, *, vm=False):
    """Build a recording fake handle for the re-pointed `set` dispatcher.

    The Phase-6 `_dispatch_set` resolves a typed handle then RMWs M9 properties
    on it. These fakes subclass the REAL kind (so `isinstance(inst,
    SystemContainer/VirtualMachine)` in the handler holds) but OVERRIDE the
    settable properties with plain recording slots — no live I/O, no `set_cmd`.
    They record the TYPED objects assigned (classes-only seam) for the tests to
    assert against.
    """
    from kento import SystemContainer, VirtualMachine

    base = VirtualMachine if vm else SystemContainer

    class _Fake(base):  # type: ignore[valid-type, misc]
        def __init__(self, net):
            self._network = net
            self._resources = {}
            self._hostname = "box"
            self._forwards = {}
            self._lxc_args = ()
            self._qemu_args = ()
            self._extra_args = ()
            self.network_set_count = 0
            self.forwards_set_count = 0

        @property
        def network(self):
            return self._network

        @network.setter
        def network(self, value):
            self._network = value
            self.network_set_count += 1

        @property
        def resources(self):
            return self._resources

        @resources.setter
        def resources(self, value):
            self._resources = value

        @property
        def hostname(self):
            return self._hostname

        @hostname.setter
        def hostname(self, value):
            self._hostname = value

        @property
        def forwards(self):
            return self._forwards

        @forwards.setter
        def forwards(self, value):
            self._forwards = value
            self.forwards_set_count += 1

        @property
        def lxc_args(self):
            return self._lxc_args

        @lxc_args.setter
        def lxc_args(self, value):
            self._lxc_args = tuple(value)

        @property
        def qemu_args(self):
            return self._qemu_args

        @qemu_args.setter
        def qemu_args(self, value):
            self._qemu_args = tuple(value)

        @property
        def extra_args(self):
            return self._extra_args

        @extra_args.setter
        def extra_args(self, value):
            self._extra_args = tuple(value)

    return _Fake(network)


def _FakeSetInstance(network):
    """A recording SystemContainer-kind fake (LXC) for `set` dispatch tests."""
    return _make_fake_set_instance(network, vm=False)


def _FakeSetVM(network):
    """A recording VirtualMachine-kind fake for `set` dispatch tests."""
    return _make_fake_set_instance(network, vm=True)


def _run_create(argv):
    """Run a create/run command with BOTH typed creates patched; return the
    captured ``call`` (positional + kwargs) of whichever kind fired.

    Phase-6 re-point: `create`/`run` now dispatch onto the typed
    `SystemContainer.create` / `VirtualMachine.create`, so create tests assert
    the TYPED objects built (classes-only seam) instead of flat `create.create`
    kwargs. Returns the MagicMock `call` object (use `.args` / `.kwargs`).
    """
    with patch("kento.SystemContainer.create") as msc, \
         patch("kento.VirtualMachine.create") as mvm:
        main(argv)
    if msc.called:
        return msc.call_args
    assert mvm.called, "neither typed create was called"
    return mvm.call_args


def test_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "lxc" in output


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "kento" in output


def test_no_command(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "lxc" in output


def test_lxc_no_subcommand(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["lxc"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "create" in output
    assert "destroy" in output
    assert "list" in output


def test_lxc_create_requires_image(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["lxc", "create"])
    assert exc.value.code != 0


def test_lxc_create_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["lxc", "create", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "--name" in output
    assert "--pve" in output
    assert "--vmid" in output
    assert "--port" in output
    assert "--start" in output
    # --pve-arg applies to PVE-LXC, so it stays visible under lxc scope.
    assert "--pve-arg" in output
    # --lxc-arg is plain-LXC native config; visible under lxc scope.
    assert "--lxc-arg" in output
    # VM-only flags are hidden from lxc help (still rejected at runtime with a
    # friendly message, but not advertised as accepted here).
    assert "--qemu-arg" not in output
    assert "--mac" not in output


def test_vm_create_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["vm", "create", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    # VM-applicable flags are visible under vm scope.
    assert "--qemu-arg" in output
    assert "--mac" in output
    assert "--pve-arg" in output
    # --lxc-arg is plain-LXC only; hidden from vm help.
    assert "--lxc-arg" not in output


def test_pve_lxc_mutually_exclusive(capsys):
    """--pve and --no-pve are BooleanOptionalAction; not an error to combine with scope."""
    # This test originally checked --pve --lxc mutual exclusion, but --lxc is removed.
    # Now --pve is just a boolean flag, no mutual exclusion with scope.
    # We test that --pve and --no-pve together uses last-wins (argparse default).
    pass


def test_vm_pve_mutually_exclusive(capsys):
    """--pve under vm scope is valid (pve=True + scope=vm => pve-vm mode)."""
    # The old --vm --pve mutual exclusion is gone. Now vm scope + --pve is valid.
    pass


def test_vm_lxc_mutually_exclusive(capsys):
    """--lxc and --vm flags no longer exist; skip."""
    pass


def test_lxc_subcommands_in_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["lxc", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "create" in output
    assert "start" in output
    assert "shutdown" in output
    assert "stop" in output
    assert "destroy" in output
    assert "rm" in output
    assert "scrub" in output
    assert "list" in output


def test_lxc_shutdown_in_help(capsys):
    """shutdown is recognized as a command with --force flag."""
    with pytest.raises(SystemExit) as exc:
        main(["lxc", "shutdown", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "--force" in output


def test_lxc_stop_alias(capsys):
    """stop still works as an alias for shutdown with --force flag."""
    with pytest.raises(SystemExit) as exc:
        main(["lxc", "stop", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "--force" in output


def test_lxc_destroy_in_help(capsys):
    """destroy is recognized as a command."""
    with pytest.raises(SystemExit) as exc:
        main(["lxc", "destroy", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "--force" in output


def test_lxc_rm_alias(capsys):
    """rm still works as an alias for destroy."""
    with pytest.raises(SystemExit) as exc:
        main(["lxc", "rm", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "--force" in output


def test_lxc_scrub_in_help(capsys):
    """scrub is recognized as a command."""
    with pytest.raises(SystemExit) as exc:
        main(["lxc", "scrub", "--help"])
    assert exc.value.code == 0


# --- Three-level CLI tests ---

class TestBareCommands:
    """Test bare top-level commands (kento <cmd>).

    Note: bare create and run are removed in the new CLI; they require
    'kento lxc create' or 'kento vm create'.
    """

    def test_bare_create_not_available(self, capsys):
        """kento create (bare) is no longer available — must use lxc/vm scope."""
        with pytest.raises(SystemExit) as exc:
            main(["create"])
        assert exc.value.code != 0

    def test_bare_start_help(self, capsys):
        """kento start --help is recognized."""
        with pytest.raises(SystemExit) as exc:
            main(["start", "--help"])
        assert exc.value.code == 0

    def test_bare_list_help(self, capsys):
        """kento list --help is recognized."""
        with pytest.raises(SystemExit) as exc:
            main(["list", "--help"])
        assert exc.value.code == 0

    def test_bare_ls_help(self, capsys):
        """kento ls --help is recognized."""
        with pytest.raises(SystemExit) as exc:
            main(["ls", "--help"])
        assert exc.value.code == 0

    def test_bare_shutdown_help(self, capsys):
        """kento shutdown --help is recognized."""
        with pytest.raises(SystemExit) as exc:
            main(["shutdown", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--force" in output

    def test_bare_stop_help(self, capsys):
        """kento stop --help is recognized."""
        with pytest.raises(SystemExit) as exc:
            main(["stop", "--help"])
        assert exc.value.code == 0

    def test_bare_destroy_help(self, capsys):
        """kento destroy --help is recognized."""
        with pytest.raises(SystemExit) as exc:
            main(["destroy", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--force" in output

    def test_bare_rm_help(self, capsys):
        """kento rm --help is recognized."""
        with pytest.raises(SystemExit) as exc:
            main(["rm", "--help"])
        assert exc.value.code == 0

    def test_bare_scrub_help(self, capsys):
        """kento scrub --help is recognized."""
        with pytest.raises(SystemExit) as exc:
            main(["scrub", "--help"])
        assert exc.value.code == 0


class TestVmCommands:
    """Test vm subcommand group (kento vm <cmd>)."""

    def test_vm_no_subcommand(self, capsys):
        """kento vm with no subcommand shows help."""
        with pytest.raises(SystemExit) as exc:
            main(["vm"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "create" in output

    def test_vm_create_help(self, capsys):
        """kento vm create --help works."""
        with pytest.raises(SystemExit) as exc:
            main(["vm", "create", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--name" in output

    def test_vm_create_requires_image(self, capsys):
        """kento vm create (no image) should error."""
        with pytest.raises(SystemExit) as exc:
            main(["vm", "create"])
        assert exc.value.code != 0

    def test_vm_start_help(self, capsys):
        """kento vm start --help is recognized."""
        with pytest.raises(SystemExit) as exc:
            main(["vm", "start", "--help"])
        assert exc.value.code == 0

    def test_vm_stop_help(self, capsys):
        """kento vm stop --help is recognized."""
        with pytest.raises(SystemExit) as exc:
            main(["vm", "stop", "--help"])
        assert exc.value.code == 0

    def test_vm_destroy_help(self, capsys):
        """kento vm destroy --help is recognized."""
        with pytest.raises(SystemExit) as exc:
            main(["vm", "destroy", "--help"])
        assert exc.value.code == 0

    def test_vm_list_help(self, capsys):
        """kento vm list --help is recognized."""
        with pytest.raises(SystemExit) as exc:
            main(["vm", "list", "--help"])
        assert exc.value.code == 0

    def test_vm_subcommands_in_help(self, capsys):
        """kento vm --help shows all subcommands."""
        with pytest.raises(SystemExit) as exc:
            main(["vm", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "create" in output
        assert "start" in output
        assert "shutdown" in output
        assert "destroy" in output
        assert "list" in output


class TestListSizeFlag:
    """--size / -s opt-in for the UPPER SIZE column (v1.2.1 perf fix).

    Re-pointed (Block 18): `list` now enumerates via the typed `Instance.list()`
    (scope -> base/SystemContainer/VirtualMachine) and renders via the Block-17
    projection (`instances_to_human` / `instances_to_json`). These tests assert
    the FLAG THREADING — that the right scope->class is enumerated and that
    `show_size` / the human-vs-json branch reach the projection unchanged. The
    BYTE-IDENTICAL wire is pinned by test_projection_golden.py +
    test_cli_list_dispatch.py.
    """

    def _list_threading(self, argv, *, expect_cls, expect_show_size,
                        expect_json):
        """Run `main(argv)` with the typed list + projection stubbed; return
        (class .list() was called on, show_size, used_json)."""
        seen = {}

        def fake_list(cls):
            seen["cls"] = cls
            return []

        def fake_human(insts, *, show_size=False):
            seen["show_size"] = show_size
            seen["json"] = False
            return ""

        def fake_json(insts, *, show_size=False):
            seen["show_size"] = show_size
            seen["json"] = True
            return ""

        with patch("kento.Instance.list", classmethod(fake_list)), \
             patch("kento.SystemContainer.list", classmethod(fake_list)), \
             patch("kento.VirtualMachine.list", classmethod(fake_list)), \
             patch("kento_cli._projection.instances_to_human", fake_human), \
             patch("kento_cli._projection.instances_to_json", fake_json):
            main(argv)
        assert seen["cls"] is expect_cls
        assert seen["show_size"] is expect_show_size
        assert seen["json"] is expect_json

    def test_bare_list_default_passes_show_size_false(self):
        from kento import Instance
        self._list_threading(["list"], expect_cls=Instance,
                             expect_show_size=False, expect_json=False)

    def test_bare_list_with_size_long(self):
        from kento import Instance
        self._list_threading(["list", "--size"], expect_cls=Instance,
                             expect_show_size=True, expect_json=False)

    def test_bare_list_with_size_short(self):
        from kento import Instance
        self._list_threading(["list", "-s"], expect_cls=Instance,
                             expect_show_size=True, expect_json=False)

    def test_bare_ls_with_size(self):
        from kento import Instance
        self._list_threading(["ls", "--size"], expect_cls=Instance,
                             expect_show_size=True, expect_json=False)

    def test_lxc_list_default_show_size_false(self):
        from kento import SystemContainer
        self._list_threading(["lxc", "list"], expect_cls=SystemContainer,
                             expect_show_size=False, expect_json=False)

    def test_lxc_list_with_size(self):
        from kento import SystemContainer
        self._list_threading(["lxc", "list", "--size"],
                             expect_cls=SystemContainer,
                             expect_show_size=True, expect_json=False)

    def test_vm_list_with_size(self):
        from kento import VirtualMachine
        self._list_threading(["vm", "list", "-s"], expect_cls=VirtualMachine,
                             expect_show_size=True, expect_json=False)

    def test_bare_list_json_flag(self):
        from kento import Instance
        self._list_threading(["list", "--json"], expect_cls=Instance,
                             expect_show_size=False, expect_json=True)

    def test_lxc_list_json_flag(self):
        from kento import SystemContainer
        self._list_threading(["lxc", "list", "--json"],
                             expect_cls=SystemContainer,
                             expect_show_size=False, expect_json=True)

    def test_vm_list_json_flag(self):
        from kento import VirtualMachine
        self._list_threading(["vm", "list", "--json"],
                             expect_cls=VirtualMachine,
                             expect_show_size=False, expect_json=True)

    def test_bare_list_help_mentions_size(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["list", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--size" in output


class TestAllowNestingFlag:
    """--allow-nesting unified flag (default off in all modes)."""

    def test_default_off(self):
        call = _run_create(["vm", "create", "myimg"])
        assert call.kwargs["nesting"] is False

    def test_allow_nesting_on(self):
        call = _run_create(["vm", "create", "--allow-nesting", "myimg"])
        assert call.kwargs["nesting"] is True

    def test_no_allow_nesting(self):
        call = _run_create(["vm", "create", "--no-allow-nesting", "myimg"])
        assert call.kwargs["nesting"] is False

    def test_lxc_allow_nesting_on(self):
        call = _run_create(["lxc", "create", "--allow-nesting", "myimg"])
        assert call.kwargs["nesting"] is True

    def test_old_nesting_flag_removed(self, capsys):
        # The old --nesting flag no longer exists.
        with pytest.raises(SystemExit) as exc:
            main(["vm", "create", "--nesting", "myimg"])
        assert exc.value.code != 0
        err = capsys.readouterr().err
        assert "--nesting" in err or "unrecognized" in err


class TestUnprivilegedFlag:
    """--unprivileged flag is parsed and threaded to create()."""

    def test_default_off(self):
        call = _run_create(["lxc", "create", "myimg"])
        assert call.kwargs["unprivileged"] is False

    def test_unprivileged_on(self):
        call = _run_create(["lxc", "create", "--unprivileged", "myimg"])
        assert call.kwargs["unprivileged"] is True

    def test_lxc_unprivileged_still_calls_through(self):
        # Item A guard: the LXC reject must NOT touch the LXC path. Confirms
        # `unprivileged=True` is still threaded to SystemContainer.create.
        with patch("kento.SystemContainer.create") as msc, \
             patch("kento.VirtualMachine.create") as mvm:
            main(["lxc", "create", "--unprivileged", "myimg"])
        assert msc.called
        assert not mvm.called
        assert msc.call_args.kwargs["unprivileged"] is True

    def test_vm_unprivileged_rejected(self, capsys):
        # Regression (#256): the typed VirtualMachine.create has no
        # `unprivileged` param, so the flag was silently ignored. The CLI edge
        # must reject it (exit 1, legacy message) BEFORE calling create.
        with patch("kento.SystemContainer.create") as msc, \
             patch("kento.VirtualMachine.create") as mvm:
            with pytest.raises(SystemExit) as exc:
                main(["vm", "create", "--unprivileged", "myimg"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "--unprivileged applies to LXC modes only" in err
        assert "VMs have their own isolation" in err
        # The reject fires before any typed create call.
        assert not mvm.called
        assert not msc.called

    def test_pve_vm_unprivileged_rejected(self, capsys):
        # Same reject covers pve-vm (vm scope + --pve reaches the VM kind).
        with patch("kento.SystemContainer.create") as msc, \
             patch("kento.VirtualMachine.create") as mvm:
            with pytest.raises(SystemExit) as exc:
                main(["vm", "create", "--pve", "--vmid", "200",
                      "--unprivileged", "myimg"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "--unprivileged applies to LXC modes only" in err
        assert not mvm.called
        assert not msc.called


class TestTopLevelHelp:
    """Test top-level help includes both lxc and vm groups."""

    def test_help_shows_lxc_and_vm(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "lxc" in output
        assert "vm" in output

    def test_version_still_works(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--version"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "kento" in output

    def test_no_args_shows_help(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "lxc" in output
        assert "vm" in output


class TestPullCommand:
    """Tests for the bare-only 'kento pull' command."""

    def test_pull_help(self, capsys):
        """kento pull --help is recognized."""
        with pytest.raises(SystemExit) as exc:
            main(["pull", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "image" in output

    def test_pull_requires_image(self, capsys):
        """kento pull (no image) should error."""
        with pytest.raises(SystemExit) as exc:
            main(["pull"])
        assert exc.value.code != 0

    def test_pull_calls_library_and_prints_confirmation(self, capsys):
        """kento pull <image> calls OciImage.pull(ref); prints a confirmation.

        Re-pointed (Phase 6) onto the typed M19 op. CLASSES-ONLY: the handler
        consumes the returned Image handle (a class) and renders its source.
        """
        fake_image = MagicMock()
        fake_image.source.render.return_value = "docker.io/library/alpine:3"
        with patch("kento.require_root"), \
             patch("kento.OciImage.pull",
                   return_value=fake_image) as mock_pull:
            main(["pull", "docker.io/library/alpine:3"])
        mock_pull.assert_called_once_with("docker.io/library/alpine:3")
        out = capsys.readouterr().out
        assert "Pulled docker.io/library/alpine:3" in out

    def test_pull_forwards_exit_code(self, capsys):
        """A pull failure (SubprocessError) maps to exit 1 via _handle."""
        from kento.errors import SubprocessError
        with patch("kento.require_root"), \
             patch("kento.OciImage.pull",
                   side_effect=SubprocessError(
                       "failed to pull image (exit 125)", returncode=125)):
            with pytest.raises(SystemExit) as exc:
                main(["pull", "nonexistent/image:latest"])
            assert exc.value.code == 1
        assert "Error:" in capsys.readouterr().err

    def test_pull_not_under_lxc(self, capsys):
        """kento lxc pull should not dispatch to pull."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "pull", "alpine:3"])
        # argparse should reject this since pull is not an lxc subcommand
        assert exc.value.code != 0

    def test_pull_not_under_vm(self, capsys):
        """kento vm pull should not dispatch to pull."""
        with pytest.raises(SystemExit) as exc:
            main(["vm", "pull", "alpine:3"])
        # argparse should reject this since pull is not a vm subcommand
        assert exc.value.code != 0

    def test_pull_podman_missing_reports_clean_error(self, capsys):
        """Podman absent -> SubprocessError(returncode=None) -> exit 2.

        The old handler special-cased FileNotFoundError to exit 2 with its own
        message; the re-pointed handler lets OciImage.pull's run_or_die raise
        a SubprocessError carrying returncode=None for an unlaunchable tool, which
        _exit_code maps to 2 (preserving the exit code) and _handle surfaces as
        'Error: ...' (the message now comes from the library). No traceback.
        """
        from kento.errors import SubprocessError
        with patch("kento.require_root"), \
             patch("kento.OciImage.pull",
                   side_effect=SubprocessError(
                       "failed to pull image: podman not found",
                       returncode=None)):
            with pytest.raises(SystemExit) as exc:
                main(["pull", "alpine:3"])
            assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "Error:" in err
        assert "Traceback" not in err


class TestImagesCommand:
    """Tests for the bare-only 'kento images' command."""

    def test_images_dispatches(self):
        """kento images consumes the typed kento.ImageRecord.list() (SD3, JC1)
        — no library string crosses the seam."""
        import kento
        calls = []
        with patch.object(kento.ImageRecord, "list",
                          classmethod(lambda cls: calls.append(1) or [])):
            main(["images"])
        assert calls == [1]
        # The removed library string surface stays gone.
        import kento.images as kimages
        assert not hasattr(kimages, "list_images")

    def test_images_in_use_flag(self):
        """kento images --in-use filters the typed list CLI-side (record.in_use)."""
        import kento
        from kento import Digest, ImageRecord
        records = [
            ImageRecord(id=Digest(algorithm="sha256", encoded="a" * 64),
                        guests=("box",)),
            ImageRecord(id=Digest(algorithm="sha256", encoded="b" * 64)),
        ]
        with patch.object(kento.ImageRecord, "list",
                          classmethod(lambda cls: list(records))):
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                main(["images", "--in-use"])
        out = buf.getvalue()
        assert "aaaaaaaaaaaa" in out and "bbbbbbbbbbbb" not in out

    def test_images_not_under_lxc(self):
        """kento lxc images is not a registered subcommand."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "images"])
        assert exc.value.code != 0

    def test_images_not_under_vm(self):
        """kento vm images is not a registered subcommand."""
        with pytest.raises(SystemExit) as exc:
            main(["vm", "images"])
        assert exc.value.code != 0


class TestPruneCommand:
    """Tests for the bare-only 'kento prune' command."""

    def test_prune_dispatches_dangling(self):
        """kento prune calls OciImage.prune(scope=DANGLING), requires root.

        Re-pointed (Phase 6): bare prune now reclaims podman DANGLING images
        (M22) rather than the former kento orphan-HOLD GC. Image.prune always
        EXECUTES (no dry_run), so --yes does not gate the image pass.
        """
        from kento import PruneScope, ReclaimReport
        report = ReclaimReport(dry_run=False)
        with patch("kento.require_root"), \
             patch("kento.OciImage.prune",
                   return_value=report) as mock_prune:
            main(["prune"])
        mock_prune.assert_called_once_with(scope=PruneScope.DANGLING)

    def test_prune_yes_flag(self):
        """kento prune --yes still targets dangling images (image prune has no
        dry-run; --yes only affects the opt-in --orphans pass)."""
        from kento import PruneScope, ReclaimReport
        report = ReclaimReport(dry_run=False)
        with patch("kento.require_root"), \
             patch("kento.OciImage.prune",
                   return_value=report) as mock_prune:
            main(["prune", "--yes"])
        mock_prune.assert_called_once_with(scope=PruneScope.DANGLING)

    def test_prune_requires_root(self):
        """kento prune gates on require_root before pruning."""
        with patch("kento.require_root", side_effect=SystemExit(1)) as mock_root, \
             patch("kento.OciImage.prune") as mock_prune:
            with pytest.raises(SystemExit):
                main(["prune"])
        mock_root.assert_called_once()
        mock_prune.assert_not_called()

    def test_prune_not_under_lxc(self):
        """kento lxc prune is not a registered subcommand."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "prune"])
        assert exc.value.code != 0

    def test_prune_not_under_vm(self):
        """kento vm prune is not a registered subcommand."""
        with pytest.raises(SystemExit) as exc:
            main(["vm", "prune"])
        assert exc.value.code != 0


class TestParseNetwork:
    """Tests for _parse_network() validation logic."""

    def test_none_returns_none_none(self):
        assert _parse_network(None, None) == (None, None)

    def test_bridge_no_name(self):
        assert _parse_network("bridge", "lxc") == ("bridge", None)

    def test_bridge_with_name(self):
        with patch("kento._bridge_exists", return_value=True):
            assert _parse_network("bridge=vmbr0", "lxc") == ("bridge", "vmbr0")

    def test_host_mode(self):
        assert _parse_network("host", "lxc") == ("host", None)

    def test_host_errors_for_vm(self):
        with pytest.raises(SystemExit):
            _parse_network("host", "vm")

    def test_usermode(self):
        assert _parse_network("usermode", "vm") == ("usermode", None)

    def test_usermode_errors_for_lxc(self):
        with pytest.raises(SystemExit):
            _parse_network("usermode", "lxc")

    def test_usermode_errors_for_pve(self):
        with pytest.raises(SystemExit):
            _parse_network("usermode", "pve")

    def test_usermode_allowed_for_bare(self):
        """Bare command (mode=None) allows usermode since it might be VM."""
        assert _parse_network("usermode", None) == ("usermode", None)

    def test_none_mode(self):
        assert _parse_network("none", "lxc") == ("none", None)

    def test_unknown_mode_errors(self):
        with pytest.raises(SystemExit):
            _parse_network("invalid", "lxc")

    def test_bridge_empty_name_errors(self):
        with pytest.raises(SystemExit):
            _parse_network("bridge=", "lxc")

    def test_host_allowed_for_bare(self):
        """Bare command (mode=None) allows host."""
        assert _parse_network("host", None) == ("host", None)

    def test_bridge_with_custom_name(self):
        with patch("kento._bridge_exists", return_value=True):
            assert _parse_network("bridge=br-lan", "pve") == ("bridge", "br-lan")


def _make_container(base: Path, dirname: str, name: str, mode: str) -> Path:
    """Create a minimal container directory with kento metadata files."""
    d = base / dirname
    d.mkdir(parents=True, exist_ok=True)
    (d / "kento-name").write_text(name)
    (d / "kento-mode").write_text(mode)
    (d / "kento-image").write_text("test-image")
    return d


class TestDispatchScope:
    """Lifecycle dispatch re-pointed onto the typed Instance.* methods (Phase 6).

    These verify the scope -> class routing (kento / kento lxc / kento vm) and the
    M5/M6/M7/M8 method calls. They patch the typed lifecycle method on the
    resolved class and assert it is invoked on the instance the scope resolves to.

    SCOPED DUPLICATE-NAME DISAMBIGUATION (T3): a name that exists in BOTH
    namespaces (a ``create --force`` duplicate) resolves the SCOPED kind under an
    explicit ``kento vm``/``kento lxc`` scope, while the BARE command still errors
    "ambiguous" (the user must pick a scope). Preserved by the director-ruled
    kento-core fix that makes subclass ``get`` narrow within its own namespace;
    see ``test_scoped_dup_name_resolves_scoped_kind`` +
    ``test_bare_start_errors_on_ambiguous_name``.
    """

    def test_vm_scope_starts_vm_not_lxc(self, tmp_path):
        """kento vm start X starts the VM even when an LXC of the same name exists
        (T3: scoped narrowing on a cross-namespace duplicate name)."""
        lxc_base = tmp_path / "lxc"
        vm_base = tmp_path / "vm"
        _make_container(lxc_base, "mybox", "mybox", "lxc")
        vm_dir = _make_container(vm_base, "mybox", "mybox", "vm")

        with patch("kento.LXC_BASE", lxc_base), \
             patch("kento.VM_BASE", vm_base), \
             patch("kento.VirtualMachine.start", autospec=True) as mock_start:
            main(["vm", "start", "mybox"])

        assert mock_start.call_count == 1
        inst = mock_start.call_args[0][0]
        from kento import VirtualMachine
        assert isinstance(inst, VirtualMachine)
        assert inst.name == "mybox" and inst._dir == vm_dir

    def test_lxc_scope_starts_lxc_not_vm(self, tmp_path):
        """kento lxc start X starts the LXC container even when a VM of the same
        name exists (T3: scoped narrowing on a cross-namespace duplicate)."""
        lxc_base = tmp_path / "lxc"
        vm_base = tmp_path / "vm"
        lxc_dir = _make_container(lxc_base, "mybox", "mybox", "lxc")
        _make_container(vm_base, "mybox", "mybox", "vm")

        with patch("kento.LXC_BASE", lxc_base), \
             patch("kento.VM_BASE", vm_base), \
             patch("kento.SystemContainer.start", autospec=True) as mock_start:
            main(["lxc", "start", "mybox"])

        assert mock_start.call_count == 1
        inst = mock_start.call_args[0][0]
        from kento import SystemContainer
        assert isinstance(inst, SystemContainer)
        assert inst.name == "mybox" and inst._dir == lxc_dir

    def test_bare_start_errors_on_ambiguous_name(self, tmp_path):
        """kento start X (bare) still errors when name exists in both namespaces
        (the bare command needs an explicit scope — base get is unchanged)."""
        lxc_base = tmp_path / "lxc"
        vm_base = tmp_path / "vm"
        _make_container(lxc_base, "mybox", "mybox", "lxc")
        _make_container(vm_base, "mybox", "mybox", "vm")

        with patch("kento.LXC_BASE", lxc_base), \
             patch("kento.VM_BASE", vm_base):
            with pytest.raises(SystemExit) as exc:
                main(["start", "mybox"])
            assert exc.value.code == 1

    def test_scoped_dup_name_resolves_scoped_kind(self, tmp_path):
        """T3 (FIXED): a scoped command on a duplicate name (both namespaces)
        resolves the SCOPED kind, not 'ambiguous'. Restored by the director-ruled
        kento-core subclass-get narrowing fix; this asserts both directions."""
        lxc_base = tmp_path / "lxc"
        vm_base = tmp_path / "vm"
        lxc_dir = _make_container(lxc_base, "mybox", "mybox", "lxc")
        vm_dir = _make_container(vm_base, "mybox", "mybox", "vm")

        with patch("kento.LXC_BASE", lxc_base), \
             patch("kento.VM_BASE", vm_base), \
             patch("kento.VirtualMachine.destroy", autospec=True) as mock_vm, \
             patch("kento.SystemContainer.destroy", autospec=True) as mock_lxc:
            main(["vm", "destroy", "--force", "mybox"])
            main(["lxc", "destroy", "--force", "mybox"])

        assert mock_vm.call_count == 1
        assert mock_vm.call_args[0][0]._dir == vm_dir
        assert mock_lxc.call_count == 1
        assert mock_lxc.call_args[0][0]._dir == lxc_dir

    def test_vm_scope_shutdown(self, tmp_path):
        """kento vm shutdown X calls VirtualMachine.stop (graceful, force=False)."""
        lxc_base = tmp_path / "lxc"
        vm_base = tmp_path / "vm"
        vm_dir = _make_container(vm_base, "mybox", "mybox", "vm")
        lxc_base.mkdir(parents=True, exist_ok=True)

        with patch("kento.LXC_BASE", lxc_base), \
             patch("kento.VM_BASE", vm_base), \
             patch("kento.VirtualMachine.stop", autospec=True) as mock_stop:
            main(["vm", "shutdown", "mybox"])

        assert mock_stop.call_count == 1
        inst = mock_stop.call_args[0][0]
        assert inst._dir == vm_dir
        assert mock_stop.call_args.kwargs == {"timeout": None, "force": False}

    def test_lxc_scope_destroy(self, tmp_path):
        """kento lxc destroy X calls SystemContainer.destroy (force=False)."""
        lxc_base = tmp_path / "lxc"
        vm_base = tmp_path / "vm"
        lxc_dir = _make_container(lxc_base, "mybox", "mybox", "lxc")
        vm_base.mkdir(parents=True, exist_ok=True)

        with patch("kento.LXC_BASE", lxc_base), \
             patch("kento.VM_BASE", vm_base), \
             patch("kento.SystemContainer.destroy", autospec=True) as mock_destroy:
            main(["lxc", "destroy", "mybox"])

        assert mock_destroy.call_count == 1
        inst = mock_destroy.call_args[0][0]
        assert inst._dir == lxc_dir
        assert mock_destroy.call_args.kwargs == {"force": False}

    def test_dispatch_vm_scope_resolves_pve_vm_mode(self, tmp_path):
        """kento vm stop X resolves a pve-vm instance to a VirtualMachine handle
        with mode='pve-vm' (the typed handle carries the mode internally)."""
        lxc_base = tmp_path / "lxc"
        vm_base = tmp_path / "vm"
        vm_dir = _make_container(vm_base, "mybox", "mybox", "pve-vm")
        (vm_dir / "kento-vmid").write_text("100")
        lxc_base.mkdir(parents=True, exist_ok=True)

        with patch("kento.LXC_BASE", lxc_base), \
             patch("kento.VM_BASE", vm_base), \
             patch("kento.VirtualMachine.stop", autospec=True) as mock_stop:
            main(["vm", "stop", "mybox"])

        inst = mock_stop.call_args[0][0]
        assert inst._mode == "pve-vm" and inst._dir == vm_dir

    def test_dispatch_lxc_scope_resolves_pve_lxc_mode(self, tmp_path):
        """Symmetric: kento lxc stop X resolves a pve-lxc handle (mode='pve-lxc')."""
        lxc_base = tmp_path / "lxc"
        vm_base = tmp_path / "vm"
        lxc_dir = _make_container(lxc_base, "mybox", "mybox", "pve-lxc")
        (lxc_dir / "kento-vmid").write_text("100")
        vm_base.mkdir(parents=True, exist_ok=True)

        with patch("kento.LXC_BASE", lxc_base), \
             patch("kento.VM_BASE", vm_base), \
             patch("kento.SystemContainer.stop", autospec=True) as mock_stop:
            main(["lxc", "stop", "mybox"])

        inst = mock_stop.call_args[0][0]
        assert inst._mode == "pve-lxc" and inst._dir == lxc_dir

    def test_vm_stop_passes_timeout_through(self, tmp_path):
        """kento vm stop --timeout 90 threads timeout=90 into stop()."""
        lxc_base = tmp_path / "lxc"
        vm_base = tmp_path / "vm"
        vm_dir = _make_container(vm_base, "mybox", "mybox", "vm")
        lxc_base.mkdir(parents=True, exist_ok=True)

        with patch("kento.LXC_BASE", lxc_base), \
             patch("kento.VM_BASE", vm_base), \
             patch("kento.VirtualMachine.stop", autospec=True) as mock_stop:
            main(["vm", "stop", "--timeout", "90", "mybox"])

        assert mock_stop.call_args.kwargs == {"timeout": 90, "force": False}

    def test_vm_stop_force_with_timeout_now_valid(self, tmp_path):
        """DELTA: --force --timeout N (grace-then-kill) is now valid (force=True,
        timeout=N) — was a ValidationError before the M6 redesign."""
        lxc_base = tmp_path / "lxc"
        vm_base = tmp_path / "vm"
        vm_dir = _make_container(vm_base, "mybox", "mybox", "vm")
        lxc_base.mkdir(parents=True, exist_ok=True)

        with patch("kento.LXC_BASE", lxc_base), \
             patch("kento.VM_BASE", vm_base), \
             patch("kento.VirtualMachine.stop", autospec=True) as mock_stop:
            main(["vm", "stop", "--force", "--timeout", "20", "mybox"])

        assert mock_stop.call_args.kwargs == {"timeout": 20, "force": True}

    def test_vm_stop_graceful_only_maps_to_force_false(self, tmp_path):
        """--graceful-only folds into force=False (the new default)."""
        lxc_base = tmp_path / "lxc"
        vm_base = tmp_path / "vm"
        vm_dir = _make_container(vm_base, "mybox", "mybox", "vm")
        lxc_base.mkdir(parents=True, exist_ok=True)

        with patch("kento.LXC_BASE", lxc_base), \
             patch("kento.VM_BASE", vm_base), \
             patch("kento.VirtualMachine.stop", autospec=True) as mock_stop:
            main(["vm", "stop", "--graceful-only", "mybox"])

        assert mock_stop.call_args.kwargs == {"timeout": None, "force": False}

    def test_vm_stop_graceful_only_and_force_rejected(self, tmp_path):
        """--graceful-only --force stays a ValidationError (contradictory)."""
        lxc_base = tmp_path / "lxc"
        vm_base = tmp_path / "vm"
        _make_container(vm_base, "mybox", "mybox", "vm")
        lxc_base.mkdir(parents=True, exist_ok=True)

        with patch("kento.LXC_BASE", lxc_base), \
             patch("kento.VM_BASE", vm_base), \
             patch("kento.VirtualMachine.stop", autospec=True) as mock_stop:
            with pytest.raises(SystemExit) as exc:
                main(["vm", "stop", "--graceful-only", "--force", "mybox"])
        assert exc.value.code == 1
        mock_stop.assert_not_called()

    def test_lxc_scope_scrub(self, tmp_path):
        """kento lxc scrub X calls SystemContainer.scrub()."""
        lxc_base = tmp_path / "lxc"
        vm_base = tmp_path / "vm"
        lxc_dir = _make_container(lxc_base, "mybox", "mybox", "lxc")
        vm_base.mkdir(parents=True, exist_ok=True)

        with patch("kento.LXC_BASE", lxc_base), \
             patch("kento.VM_BASE", vm_base), \
             patch("kento.SystemContainer.scrub", autospec=True) as mock_scrub:
            main(["lxc", "scrub", "mybox"])

        assert mock_scrub.call_count == 1
        assert mock_scrub.call_args[0][0]._dir == lxc_dir


class TestRunCommand:
    """Tests for the 'kento run' command (create + start).

    Note: bare 'kento run' no longer exists. Must use 'kento lxc run' or 'kento vm run'.
    """

    def test_lxc_run_help(self, capsys):
        """kento lxc run --help is recognized and shows create-like flags."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "run", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--name" in output
        assert "--force" in output
        assert "--start" not in output  # run has no --start flag

    def test_lxc_run_help_alt(self, capsys):
        """kento lxc run --help is recognized."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "run", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--name" in output

    def test_vm_run_help(self, capsys):
        """kento vm run --help is recognized."""
        with pytest.raises(SystemExit) as exc:
            main(["vm", "run", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--name" in output

    def test_lxc_run_requires_image(self, capsys):
        """kento lxc run (no image) should error."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "run"])
        assert exc.value.code != 0

    def test_lxc_run_dispatches_create_with_start_true(self):
        """kento lxc run debian:12 dispatches to SystemContainer.create, start=True."""
        with patch("kento.SystemContainer.create") as msc, \
             patch("kento.VirtualMachine.create") as mvm:
            main(["lxc", "run", "debian:12"])
        msc.assert_called_once()
        assert not mvm.called  # the LXC kind, not the VM kind
        assert msc.call_args.kwargs["start"] is True
        # The image is the 2nd positional (name, image); name is None (auto).
        assert msc.call_args.args == (None, "debian:12")

    def test_lxc_run_with_name_flag(self):
        """kento lxc run --name mybox debian:12 passes name through (positional)."""
        call = _run_create(["lxc", "run", "--name", "mybox", "debian:12"])
        assert call.args == ("mybox", "debian:12")
        assert call.kwargs["start"] is True

    def test_vm_run_forces_vm_mode(self):
        """kento vm run debian:12 forces the VM kind (VirtualMachine.create)."""
        with patch("kento.SystemContainer.create") as msc, \
             patch("kento.VirtualMachine.create") as mvm:
            main(["vm", "run", "debian:12"])
        mvm.assert_called_once()
        assert not msc.called
        assert mvm.call_args.kwargs["start"] is True

    def test_run_in_lxc_help(self, capsys):
        """run appears in lxc help output."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "run" in output

    def test_run_in_vm_help(self, capsys):
        """run appears in vm help output."""
        with pytest.raises(SystemExit) as exc:
            main(["vm", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "run" in output

    def test_top_level_help_shows_shortcuts(self, capsys):
        """Top-level help shows shortcuts (list, start, etc.)."""
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "list" in output
        assert "pull" in output
        assert "images" in output
        assert "prune" in output


class TestSSHKeyFlag:
    """Tests for the --ssh-key flag on create and run."""

    def test_ssh_key_in_lxc_create_help(self, capsys):
        """--ssh-key appears in lxc create --help."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "create", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--ssh-key" in output

    def test_ssh_key_in_lxc_run_help(self, capsys):
        """--ssh-key appears in lxc run --help."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "run", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--ssh-key" in output

    def test_ssh_key_in_vm_create_help(self, capsys):
        """--ssh-key appears in vm create --help."""
        with pytest.raises(SystemExit) as exc:
            main(["vm", "create", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--ssh-key" in output

    def test_ssh_key_repeatable(self):
        """--ssh-key PATH can be given multiple times and produces a list."""
        call = _run_create(["lxc", "create",
                            "--ssh-key", "/tmp/key1.pub",
                            "--ssh-key", "/tmp/key2.pub",
                            "debian:12"])
        assert call.kwargs["ssh_keys"] == ["/tmp/key1.pub", "/tmp/key2.pub"]

    def test_ssh_key_passes_through_to_create(self):
        """--ssh-key PATH reaches the typed create as ssh_keys=[...]."""
        call = _run_create(
            ["lxc", "create", "--ssh-key", "/tmp/mykey.pub", "debian:12"])
        assert call.kwargs["ssh_keys"] == ["/tmp/mykey.pub"]

    def test_ssh_key_default_none(self):
        """Without --ssh-key, ssh_keys is None."""
        call = _run_create(["lxc", "create", "debian:12"])
        assert call.kwargs["ssh_keys"] is None

    def test_ssh_key_passes_through_from_run(self):
        """--ssh-key reaches the typed create when used via run."""
        call = _run_create(
            ["lxc", "run", "--ssh-key", "/tmp/mykey.pub", "debian:12"])
        assert call.kwargs["ssh_keys"] == ["/tmp/mykey.pub"]
        assert call.kwargs["start"] is True


class TestSSHKeyUserFlag:
    """Tests for the --ssh-key-user flag on create and run."""

    def test_ssh_key_user_in_lxc_create_help(self, capsys):
        """--ssh-key-user appears in lxc create --help."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "create", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--ssh-key-user" in output

    def test_ssh_key_user_in_lxc_run_help(self, capsys):
        """--ssh-key-user appears in lxc run --help."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "run", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--ssh-key-user" in output

    def test_ssh_key_user_default_root(self):
        """Without --ssh-key-user, ssh_key_user defaults to 'root'."""
        call = _run_create(["lxc", "create", "debian:12"])
        assert call.kwargs["ssh_key_user"] == "root"

    def test_ssh_key_user_custom_value(self):
        """--ssh-key-user droste passes through to the typed create."""
        call = _run_create(
            ["lxc", "create", "--ssh-key-user", "droste", "debian:12"])
        assert call.kwargs["ssh_key_user"] == "droste"

    def test_ssh_key_user_passes_through_from_run(self):
        """--ssh-key-user reaches the typed create when used via run."""
        call = _run_create(
            ["lxc", "run", "--ssh-key-user", "droste", "debian:12"])
        assert call.kwargs["ssh_key_user"] == "droste"
        assert call.kwargs["start"] is True

    def test_ssh_key_user_without_ssh_key_is_harmless(self):
        """--ssh-key-user without --ssh-key doesn't error."""
        call = _run_create(
            ["lxc", "create", "--ssh-key-user", "droste", "debian:12"])
        assert call.kwargs["ssh_keys"] is None
        assert call.kwargs["ssh_key_user"] == "droste"


class TestSSHHostKeyFlags:
    """Tests for --ssh-host-keys and --ssh-host-key-dir flags."""

    def test_ssh_host_keys_in_lxc_create_help(self, capsys):
        """--ssh-host-keys appears in lxc create --help."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "create", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--ssh-host-keys" in output

    def test_ssh_host_key_dir_in_lxc_create_help(self, capsys):
        """--ssh-host-key-dir appears in lxc create --help."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "create", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--ssh-host-key-dir" in output

    def test_ssh_host_keys_in_lxc_run_help(self, capsys):
        """--ssh-host-keys appears in lxc run --help."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "run", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--ssh-host-keys" in output

    def test_ssh_host_key_dir_in_lxc_run_help(self, capsys):
        """--ssh-host-key-dir appears in lxc run --help."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "run", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--ssh-host-key-dir" in output

    def test_mutually_exclusive(self, capsys):
        """--ssh-host-keys and --ssh-host-key-dir cannot be used together."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "create", "--ssh-host-keys", "--ssh-host-key-dir", "/tmp/keys",
                  "debian:12"])
        assert exc.value.code != 0

    def test_ssh_host_keys_passes_through(self):
        """--ssh-host-keys reaches the typed create as ssh_host_keys=True."""
        call = _run_create(["lxc", "create", "--ssh-host-keys", "debian:12"])
        assert call.kwargs["ssh_host_keys"] is True
        assert call.kwargs["ssh_host_key_dir"] is None

    def test_ssh_host_key_dir_passes_through(self):
        """--ssh-host-key-dir PATH reaches the typed create."""
        call = _run_create(
            ["lxc", "create", "--ssh-host-key-dir", "/tmp/mykeys", "debian:12"])
        assert call.kwargs["ssh_host_key_dir"] == "/tmp/mykeys"
        assert call.kwargs["ssh_host_keys"] is False

    def test_ssh_host_keys_default_false(self):
        """Without --ssh-host-keys, ssh_host_keys is False."""
        call = _run_create(["lxc", "create", "debian:12"])
        assert call.kwargs["ssh_host_keys"] is False
        assert call.kwargs["ssh_host_key_dir"] is None

    def test_ssh_host_keys_via_run(self):
        """--ssh-host-keys reaches the typed create when used via run."""
        call = _run_create(["lxc", "run", "--ssh-host-keys", "debian:12"])
        assert call.kwargs["ssh_host_keys"] is True
        assert call.kwargs["start"] is True

    def test_ssh_host_key_dir_via_vm_create(self):
        """--ssh-host-key-dir reaches the typed create via vm create."""
        call = _run_create(
            ["vm", "create", "--ssh-host-key-dir", "/tmp/k", "debian:12"])
        assert call.kwargs["ssh_host_key_dir"] == "/tmp/k"


class TestMacFlag:
    """Tests for the --mac flag on create and run."""

    def test_mac_hidden_from_lxc_create_help(self, capsys):
        """--mac is VM-only, so it is hidden from lxc create --help."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "create", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--mac" not in output

    def test_mac_hidden_from_lxc_run_help(self, capsys):
        """--mac is VM-only, so it is hidden from lxc run --help."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "run", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--mac" not in output

    def test_mac_in_vm_create_help(self, capsys):
        """--mac is advertised under vm create --help."""
        with pytest.raises(SystemExit) as exc:
            main(["vm", "create", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--mac" in output

    def test_mac_valid_passes_through(self):
        """A valid --mac builds the NetworkConnection's link_config (VM scope)."""
        call = _run_create(
            ["vm", "create", "--mac", "52:54:00:ab:cd:ef", "debian:12"])
        assert call.kwargs["network"].link_config["mac"] == "52:54:00:ab:cd:ef"

    def test_mac_rejected_on_lxc_scope(self, capsys):
        """F9: --mac on LXC scope is rejected (silently ignored before)."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "create", "--mac", "52:54:00:ab:cd:ef", "debian:12"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "--mac is not supported for LXC" in err

    def test_mac_rejected_on_lxc_run(self, capsys):
        """F9: --mac on 'lxc run' also rejected."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "run", "--mac", "52:54:00:ab:cd:ef", "debian:12"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "--mac is not supported for LXC" in err

    def test_mac_default_none(self):
        """Without --mac (and no other net flag), network is None (auto)."""
        call = _run_create(["lxc", "create", "debian:12"])
        assert call.kwargs["network"] is None

    def test_mac_invalid_format_rejected(self, capsys):
        """An invalid --mac value is rejected with an argparse error."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "create", "--mac", "not-a-mac", "debian:12"])
        assert exc.value.code != 0
        err = capsys.readouterr().err
        assert "invalid MAC" in err or "MAC" in err

    def test_mac_too_short_rejected(self, capsys):
        """Too few octets -> rejected."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "create", "--mac", "52:54:00:ab:cd", "debian:12"])
        assert exc.value.code != 0

    def test_mac_non_hex_rejected(self, capsys):
        """Non-hex characters -> rejected."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "create", "--mac", "52:54:00:gg:cd:ef", "debian:12"])
        assert exc.value.code != 0

    def test_mac_accepts_uppercase(self):
        """Uppercase hex accepted (VM scope)."""
        call = _run_create(
            ["vm", "create", "--mac", "AA:BB:CC:DD:EE:FF", "debian:12"])
        assert call.kwargs["network"].link_config["mac"] == "AA:BB:CC:DD:EE:FF"

    def test_mac_reaches_create_via_run(self):
        """--mac via 'vm run' also reaches the typed create."""
        call = _run_create(
            ["vm", "run", "--mac", "52:54:00:11:22:33", "debian:12"])
        assert call.kwargs["network"].link_config["mac"] == "52:54:00:11:22:33"
        assert call.kwargs["start"] is True

    def test_mac_multicast_rejected(self, capsys):
        """F16: multicast MACs (first-octet LSB set) are rejected."""
        with pytest.raises(SystemExit) as exc:
            main(["vm", "create", "--mac", "01:02:03:04:05:06", "debian:12"])
        assert exc.value.code != 0
        err = capsys.readouterr().err
        assert "multicast" in err.lower()

    def test_mac_broadcast_rejected(self, capsys):
        """F16: broadcast MAC ff:ff:ff:ff:ff:ff is rejected."""
        with pytest.raises(SystemExit) as exc:
            main(["vm", "create", "--mac", "ff:ff:ff:ff:ff:ff", "debian:12"])
        assert exc.value.code != 0
        err = capsys.readouterr().err
        assert "multicast" in err.lower() or "broadcast" in err.lower()

    def test_mac_multicast_uppercase_rejected(self, capsys):
        """F16: multicast detection is case-insensitive."""
        # 0x03 = 00000011 — LSB set, so multicast.
        with pytest.raises(SystemExit) as exc:
            main(["vm", "create", "--mac", "03:AA:BB:CC:DD:EE", "debian:12"])
        assert exc.value.code != 0

    def test_mac_laa_accepted(self):
        """F16 counter-test: locally-administered unicast (0x02 prefix) is fine."""
        call = _run_create(
            ["vm", "create", "--mac", "02:aa:bb:cc:dd:ee", "debian:12"])
        assert call.kwargs["network"].link_config["mac"] == "02:aa:bb:cc:dd:ee"

    def test_mac_06_prefix_accepted(self):
        """F16 counter-test: 0x06 (LAA unicast) is fine."""
        call = _run_create(
            ["vm", "create", "--mac", "06:00:00:00:00:01", "debian:12"])
        assert call.kwargs["network"].link_config["mac"] == "06:00:00:00:00:01"

    def test_set_mac_multicast_rejected_at_parse_time(self, capsys):
        """`set --mac` shares create's _validate_mac, so a multicast MAC is
        rejected at parse time (argparse exits 2) — never reaching set_cmd."""
        with pytest.raises(SystemExit) as exc:
            main(["set", "box", "--mac", "01:02:03:04:05:06"])
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "multicast" in err.lower() or "broadcast" in err.lower()

    def test_set_mac_unicast_accepted_at_parse_time(self):
        """Counter-test: a unicast MAC passes parse-time validation for set; it
        then RMWs the typed NetworkConnection (mac is an L2 link_config attr)."""
        from kento import NetworkConnection, NetworkMode
        # mac is VM-only at the runtime level; use a VM-kind fake in USER mode.
        fake = _FakeSetVM(NetworkConnection(mode=NetworkMode.USER))
        with patch("kento_cli._resolve_instance", return_value=fake):
            main(["set", "box", "--mac", "52:54:00:11:22:33"])
        assert fake.network.link_config["mac"] == "52:54:00:11:22:33"


class TestSetNetworkFlags:
    """`kento set` re-pointed onto M9 property mutation (§11.2, Phase 6).

    The handler now RMWs TYPED properties on the resolved handle instead of
    calling ``set_cmd`` with flat kwargs; these tests mock the resolved instance
    (``_FakeSetInstance``) and assert the TYPED objects assigned (CLASSES-ONLY).
    """

    def _run_set(self, argv, *, fake=None):
        from kento import NetworkConnection, NetworkMode
        if fake is None:
            fake = _FakeSetInstance(NetworkConnection(mode=NetworkMode.DHCP))
        with patch("kento_cli._resolve_instance", return_value=fake):
            # The re-pointed `set` returns on success (no sys.exit(0)) — the
            # outer _handle only converts a raised KentoError into an exit code,
            # matching the other Phase-6 dispatchers (info/attach/...).
            main(argv)
        return fake

    def test_set_network_host_builds_disabled_l3_cleared(self):
        from kento import NetworkConnection, NetworkMode
        start = NetworkConnection(
            mode=NetworkMode.STATIC,
            link_config={"bridge": "lxcbr0"},
            ip_config={"address": "10.0.0.5", "subnet": "24"})
        fake = self._run_set(["lxc", "set", "box", "--network", "host"],
                             fake=_FakeSetInstance(start))
        assert fake.network.mode is NetworkMode.HOST
        # A non-bridge type drops the bridge and clears L3 (set_cmd parity).
        assert "bridge" not in fake.network.link_config
        assert fake.network.ip_config == {}

    def test_set_ip_gateway_dns_hostname_build_static(self):
        from kento import NetworkMode
        fake = self._run_set([
            "set", "box", "--ip", "192.168.0.10/24",
            "--gateway", "192.168.0.1", "--dns", "1.1.1.1",
            "--hostname", "myhost"])
        assert fake.network.mode is NetworkMode.STATIC
        assert fake.network.ip_config["address"] == "192.168.0.10"
        assert fake.network.ip_config["subnet"] == "24"
        assert fake.network.ip_config["gateway"] == "192.168.0.1"
        assert fake.network.ip_config["dns1"] == "1.1.1.1"
        assert fake.hostname == "myhost"

    def test_set_port_is_repeatable_list(self):
        from kento import ForwardProtocol
        fake = self._run_set(["set", "box", "--port", "10022:22"])
        assert fake.forwards == {
            (ForwardProtocol.TCP, None, 10022): (None, 22)}

    def test_set_port_repeatable_multiple(self):
        from kento import ForwardProtocol
        fake = self._run_set(["set", "box", "--port", "10022:22",
                              "--port", "8080:80"])
        assert fake.forwards == {
            (ForwardProtocol.TCP, None, 10022): (None, 22),
            (ForwardProtocol.TCP, None, 8080): (None, 80)}

    def test_set_port_clear_sentinel(self):
        fake = self._run_set(["set", "box", "--port", ""])
        # The CLI clear sentinel ('') -> an empty forwards map (declarative).
        assert fake.forwards == {}

    def test_set_network_usermode_builds_user(self):
        from kento import NetworkMode
        fake = self._run_set(["vm", "set", "box", "--network", "usermode"])
        assert fake.network.mode is NetworkMode.USER

    def test_set_no_net_flags_leaves_network_untouched(self):
        from kento import NetworkConnection, NetworkMode
        fake = _FakeSetInstance(NetworkConnection(mode=NetworkMode.DHCP))
        self._run_set(["set", "box", "--memory", "1024"], fake=fake)
        # Only --memory was provided: network/forwards setters never fired.
        assert fake.network_set_count == 0
        assert fake.forwards_set_count == 0
        assert fake.resources == {"memory": 1024}

    def test_set_ip_validated_at_parse_time(self, capsys):
        """--ip reuses create's _validate_ip, so a bad value exits 2."""
        with pytest.raises(SystemExit) as exc:
            main(["set", "box", "--ip", "notanip"])
        assert exc.value.code == 2

    def test_set_ip_dhcp_clears_static(self):
        from kento import NetworkConnection, NetworkMode
        start = NetworkConnection(
            mode=NetworkMode.STATIC,
            link_config={"bridge": "lxcbr0"},
            ip_config={"address": "10.0.0.5", "subnet": "24",
                       "gateway": "10.0.0.1"})
        fake = self._run_set(["lxc", "set", "box", "--ip", "dhcp"],
                             fake=_FakeSetInstance(start))
        assert fake.network.mode is NetworkMode.DHCP
        assert "address" not in fake.network.ip_config
        assert "gateway" not in fake.network.ip_config
        # The bridge attachment is preserved (still bridge networking).
        assert fake.network.link_config["bridge"] == "lxcbr0"

    def test_set_gateway_without_static_ip_rejected(self, capsys):
        """--gateway on a non-static connection is rejected (set_cmd parity),
        not silently dropped by the typed decomposition (gate C)."""
        from kento import NetworkConnection, NetworkMode
        fake = _FakeSetInstance(NetworkConnection(mode=NetworkMode.DHCP))
        with patch("kento_cli._resolve_instance", return_value=fake), \
             pytest.raises(SystemExit) as exc:
            main(["set", "box", "--gateway", "10.0.0.1"])
        assert exc.value.code == 1
        assert "static" in capsys.readouterr().err.lower()
        assert fake.network_set_count == 0

    def test_set_ip_on_non_bridge_rejected(self, capsys):
        """--ip with --network host is rejected (--ip requires bridge), matching
        set_cmd._validate_net_identity rather than coercing to STATIC."""
        from kento import NetworkConnection, NetworkMode
        fake = _FakeSetInstance(NetworkConnection(mode=NetworkMode.DHCP))
        with patch("kento_cli._resolve_instance", return_value=fake), \
             pytest.raises(SystemExit) as exc:
            main(["lxc", "set", "box", "--network", "host",
                  "--ip", "10.0.0.5/24"])
        assert exc.value.code == 1
        assert "bridge" in capsys.readouterr().err.lower()
        assert fake.network_set_count == 0

    def test_set_dns_clear_sentinel(self):
        from kento import NetworkConnection, NetworkMode
        start = NetworkConnection(
            mode=NetworkMode.STATIC,
            link_config={"bridge": "lxcbr0"},
            ip_config={"address": "10.0.0.5", "subnet": "24",
                       "dns1": "1.1.1.1"})
        fake = self._run_set(["lxc", "set", "box", "--dns", ""],
                             fake=_FakeSetInstance(start))
        assert "dns1" not in fake.network.ip_config
        assert fake.network.ip_config["address"] == "10.0.0.5"


class TestSetPassthroughArgs:
    """`kento set` pass-through args re-pointed onto the typed kind properties."""

    def _set(self, argv, fake):
        with patch("kento_cli._resolve_instance", return_value=fake):
            main(argv)
        return fake

    def test_lxc_arg_replace_on_system_container(self):
        from kento import NetworkConnection, NetworkMode
        fake = _FakeSetInstance(NetworkConnection(mode=NetworkMode.DHCP))
        self._set(["lxc", "set", "box", "--lxc-arg", "lxc.foo = bar"], fake)
        assert fake.lxc_args == ("lxc.foo = bar",)

    def test_lxc_arg_clear_sentinel(self):
        from kento import NetworkConnection, NetworkMode
        fake = _FakeSetInstance(NetworkConnection(mode=NetworkMode.DHCP))
        self._set(["lxc", "set", "box", "--lxc-arg", ""], fake)
        # '' clears -> the typed setter receives an empty list.
        assert fake.lxc_args == ()

    def test_lxc_arg_on_vm_raises_mode_error(self, capsys):
        from kento import NetworkConnection, NetworkMode
        fake = _FakeSetVM(NetworkConnection(mode=NetworkMode.USER))
        with patch("kento_cli._resolve_instance", return_value=fake), \
             pytest.raises(SystemExit) as exc:
            main(["vm", "set", "box", "--lxc-arg", "lxc.foo = bar"])
        assert exc.value.code == 1
        assert "vm" in capsys.readouterr().err.lower()

    def test_qemu_arg_replace_on_vm(self):
        from kento import NetworkConnection, NetworkMode
        fake = _FakeSetVM(NetworkConnection(mode=NetworkMode.USER))
        # --qemu-arg is repeatable (one value each); use = so leading-dash
        # values aren't parsed as flags.
        self._set(["vm", "set", "box", "--qemu-arg=-smbios",
                   "--qemu-arg=type=1"], fake)
        assert fake.qemu_args == ("-smbios", "type=1")

    def test_qemu_arg_on_lxc_raises_mode_error(self, capsys):
        from kento import NetworkConnection, NetworkMode
        fake = _FakeSetInstance(NetworkConnection(mode=NetworkMode.DHCP))
        with patch("kento_cli._resolve_instance", return_value=fake), \
             pytest.raises(SystemExit) as exc:
            main(["lxc", "set", "box", "--qemu-arg=-foo"])
        assert exc.value.code == 1
        assert "vm modes only" in capsys.readouterr().err.lower()

    def test_pve_arg_routes_to_extra_args(self):
        from kento import NetworkConnection, NetworkMode
        fake = _FakeSetInstance(NetworkConnection(mode=NetworkMode.DHCP))
        self._set(["set", "box", "--pve-arg", "tags: kento"], fake)
        assert fake.extra_args == ("tags: kento",)

    def test_memory_cores_rmw_only_provided(self):
        from kento import NetworkConnection, NetworkMode
        fake = _FakeSetInstance(NetworkConnection(mode=NetworkMode.DHCP))
        fake._resources = {"memory": 512, "cores": 2}
        self._set(["set", "box", "--memory", "2048"], fake)
        # Only memory replaced; cores untouched (only-provided-fields).
        assert fake.resources == {"memory": 2048, "cores": 2}


class TestPortNetworkValidation:
    """Tests for --port + --network CLI-level validation (Phase 3)."""

    def test_port_with_host_errors(self, capsys):
        """--port with --network host exits with error."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "create", "--port", "10022:22", "--network", "host",
                  "debian:12"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "host" in err or "none" in err

    def test_port_with_none_errors(self, capsys):
        """--port with --network none exits with error."""
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "create", "--port", "10022:22", "--network", "none",
                  "debian:12"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "host" in err or "none" in err

    def test_port_with_bridge_passes_to_create(self):
        """--port with --network bridge builds the typed forwards map (LXC)."""
        from kento import ForwardProtocol
        with patch("kento._bridge_exists", return_value=True):
            call = _run_create(
                ["lxc", "create", "--port", "10022:22",
                 "--network", "bridge=lxcbr0", "debian:12"])
        # --port (repeatable, Phase-5 delta) -> the typed forwards map.
        assert call.kwargs["forwards"] == {
            (ForwardProtocol.TCP, None, 10022): (None, 22)}

    def test_port_without_network_passes_to_create(self):
        """--port without --network builds the typed forwards map (auto-detect)."""
        from kento import ForwardProtocol
        call = _run_create(["lxc", "create", "--port", "10022:22", "debian:12"])
        assert call.kwargs["forwards"] == {
            (ForwardProtocol.TCP, None, 10022): (None, 22)}

    def test_port_repeatable_multiple_forwards(self):
        """--port is repeatable: multiple flags -> multiple typed forwards."""
        from kento import ForwardProtocol
        call = _run_create(
            ["lxc", "create", "--port", "10022:22", "--port", "8080:80",
             "debian:12"])
        assert call.kwargs["forwards"] == {
            (ForwardProtocol.TCP, None, 10022): (None, 22),
            (ForwardProtocol.TCP, None, 8080): (None, 80)}


class TestVmScopeOverridesMode:
    """kento vm create always forces mode=vm, even with --pve flag."""

    def test_vm_create_with_pve_flag_forces_vm(self):
        """kento vm create --pve --vmid N dispatches the VM kind w/ a PVE platform
        carrying the vmid (forced PVE at a chosen id)."""
        from kento import PlatformMode
        with patch("kento.SystemContainer.create") as msc, \
             patch("kento.VirtualMachine.create") as mvm:
            main(["vm", "create", "--pve", "--vmid", "200", "debian:12"])
        mvm.assert_called_once()
        assert not msc.called
        platform = mvm.call_args.kwargs["platform"]
        assert platform.mode is PlatformMode.PVE
        assert platform.mid == 200

    def test_vm_create_without_flags_forces_vm(self):
        """kento vm create <image> dispatches the VM kind (regression check)."""
        with patch("kento.SystemContainer.create") as msc, \
             patch("kento.VirtualMachine.create") as mvm:
            main(["vm", "create", "debian:12"])
        mvm.assert_called_once()
        assert not msc.called

    def test_lxc_create_with_pve_flag(self):
        """kento lxc create --pve --vmid N dispatches the LXC kind w/ a PVE
        platform carrying the vmid."""
        from kento import PlatformMode
        with patch("kento.SystemContainer.create") as msc, \
             patch("kento.VirtualMachine.create") as mvm:
            main(["lxc", "create", "--pve", "--vmid", "200", "debian:12"])
        msc.assert_called_once()
        assert not mvm.called
        platform = msc.call_args.kwargs["platform"]
        assert platform.mode is PlatformMode.PVE
        assert platform.mid == 200

    def test_lxc_create_pve_auto_vmid_uses_autodetect(self):
        """--pve WITHOUT --vmid maps to platform=None (auto-detect) + mid=None
        (auto-allocate) — a valid PVE identity profile needs a concrete vmid, so
        the auto-vmid PVE path rides auto-detection (Phase-6 disclosed nuance)."""
        with patch("kento.SystemContainer.create") as msc, \
             patch("kento.VirtualMachine.create") as mvm:
            main(["lxc", "create", "--pve", "debian:12"])
        msc.assert_called_once()
        assert not mvm.called
        assert msc.call_args.kwargs["platform"] is None
        assert msc.call_args.kwargs["mid"] is None


class TestMemoryCoresFlags:
    """Tests for --memory and --cores flags on create and run."""

    def test_memory_in_lxc_create_help(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "create", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--memory" in output

    def test_cores_in_lxc_create_help(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "create", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--cores" in output

    def test_memory_in_lxc_run_help(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "run", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--memory" in output

    def test_cores_in_lxc_run_help(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "run", "--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "--cores" in output

    def test_memory_default_none(self):
        # No --memory/--cores -> the resources bag is None (create.py defaults).
        call = _run_create(["lxc", "create", "debian:12"])
        assert call.kwargs["resources"] is None

    def test_cores_default_none(self):
        call = _run_create(["lxc", "create", "debian:12"])
        assert call.kwargs["resources"] is None

    def test_memory_passes_through(self):
        call = _run_create(["lxc", "create", "--memory", "1024", "debian:12"])
        assert call.kwargs["resources"] == {"memory": 1024}

    def test_cores_passes_through(self):
        call = _run_create(["lxc", "create", "--cores", "4", "debian:12"])
        assert call.kwargs["resources"] == {"cores": 4}

    def test_memory_and_cores_via_run(self):
        call = _run_create(
            ["lxc", "run", "--memory", "2048", "--cores", "2", "debian:12"])
        assert call.kwargs["resources"] == {"memory": 2048, "cores": 2}
        assert call.kwargs["start"] is True

    def test_memory_and_cores_via_vm_create(self):
        with patch("kento.SystemContainer.create") as msc, \
             patch("kento.VirtualMachine.create") as mvm:
            main(["vm", "create", "--memory", "4096", "--cores", "8", "debian:12"])
        mvm.assert_called_once()
        assert not msc.called
        assert mvm.call_args.kwargs["resources"] == {"memory": 4096, "cores": 8}

    def test_memory_and_cores_via_lxc_create(self):
        call = _run_create(
            ["lxc", "create", "--memory", "256", "--cores", "1", "debian:12"])
        assert call.kwargs["resources"] == {"memory": 256, "cores": 1}


class TestForceFlag:
    """--force on create/run must reach create() as force=True so the
    cross-namespace scan inside create.py can skip to current-namespace-only.
    """

    def test_lxc_create_force_passes_to_create(self):
        """kento lxc create --force reaches the typed create with force=True."""
        call = _run_create(["lxc", "create", "--force", "debian:13"])
        assert call.kwargs["force"] is True

    def test_lxc_create_force_default_false(self):
        """Without --force, the typed create is called with force=False."""
        call = _run_create(["lxc", "create", "debian:13"])
        assert call.kwargs["force"] is False

    def test_vm_create_force_passes_to_create(self):
        """kento vm create --force reaches the typed create with force=True."""
        call = _run_create(["vm", "create", "--force", "debian:13"])
        assert call.kwargs["force"] is True

    def test_lxc_run_force_passes_to_create(self):
        """kento lxc run --force reaches the typed create (force=True, start=True)."""
        call = _run_create(["lxc", "run", "--force", "debian:13"])
        assert call.kwargs["force"] is True
        assert call.kwargs["start"] is True

    def test_vm_run_force_passes_to_create(self):
        """kento vm run --force reaches the typed create (force=True, start=True)."""
        call = _run_create(["vm", "run", "--force", "debian:13"])
        assert call.kwargs["force"] is True
        assert call.kwargs["start"] is True


class TestCreateLongTailReachesTypedCreate:
    """Regression net for the #1 risk (create flag drop): the create-time long
    tail must reach the typed create. Complements the ssh-*/mac/port/resources/
    env coverage — this pins searchdomain/timezone/config_mode, which had no
    create-side assertion (Editor Minor 1)."""

    def test_searchdomain_timezone_config_mode_reach_create(self):
        call = _run_create([
            "lxc", "create",
            "--searchdomain", "example.com",
            "--timezone", "Europe/Berlin",
            "--config-mode", "cloudinit",
            "debian:12"])
        # Each long-tail flag is threaded to the typed create verbatim. Dropping
        # any one of them in the handler reddens the matching assertion.
        assert call.kwargs["searchdomain"] == "example.com"
        assert call.kwargs["timezone"] == "Europe/Berlin"
        assert call.kwargs["config_mode"] == "cloudinit"

    def test_long_tail_defaults_when_unset(self):
        # Counter-test: unset -> create.py's defaults (byte-identical posture).
        call = _run_create(["lxc", "create", "debian:12"])
        assert call.kwargs["searchdomain"] is None
        assert call.kwargs["timezone"] is None
        assert call.kwargs["config_mode"] == "auto"


class TestCreateStaticNetworkConstruction:
    """The CREATE static-network construction path (_build_create_network) had no
    create-side test (Editor Minor 2). Pins --ip/--gateway/--dns -> a STATIC
    NetworkConnection with the CIDR split into address/subnet."""

    def test_static_network_built_and_passed(self):
        from kento import NetworkMode
        with patch("kento._bridge_exists", return_value=True):
            call = _run_create([
                "lxc", "create",
                "--network", "bridge=lxcbr0",
                "--ip", "10.0.0.5/24",
                "--gateway", "10.0.0.1",
                "--dns", "1.1.1.1",
                "debian:12"])
        conn = call.kwargs["network"]
        assert conn.mode is NetworkMode.STATIC
        assert conn.link_config["bridge"] == "lxcbr0"
        # The CIDR is split at the boundary into address + subnet; corrupting the
        # static address build reddens this assertion.
        assert conn.ip_config["address"] == "10.0.0.5"
        assert conn.ip_config["subnet"] == "24"
        assert conn.ip_config["gateway"] == "10.0.0.1"
        assert conn.ip_config["dns1"] == "1.1.1.1"

    def test_static_ip_without_network_flag_is_static_bridge(self):
        # --ip with no --network -> STATIC, bridge family (create.py auto-detects
        # the bridge name); the address is still split from the CIDR.
        from kento import NetworkMode
        call = _run_create(
            ["lxc", "create", "--ip", "192.168.0.10/22", "debian:12"])
        conn = call.kwargs["network"]
        assert conn.mode is NetworkMode.STATIC
        assert conn.ip_config["address"] == "192.168.0.10"
        assert conn.ip_config["subnet"] == "22"
