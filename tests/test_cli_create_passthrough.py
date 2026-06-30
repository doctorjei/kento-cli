"""CLI-level tests for pass-through flags --qemu-arg / --lxc-arg / --pve-arg.

Covers the argparse surface (kento_cli.main), mode-specific rejection, and
denylist validation at the CLI layer. Storage/persistence tests live in
kento-core (TestQemuArgStorage, TestLxcArgStorage, TestPveArgStorage).
"""

from unittest.mock import patch, MagicMock

import pytest

from kento_cli import main
from test_cli import _run_create


# ---------- Argparse / CLI-level tests ----------


class TestKernelInitrdCli:
    """--kernel/--initrd: VM scope only (boot-source override, §8 Phase A)."""

    def test_kernel_in_vm_create_help(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["vm", "create", "--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "--kernel" in out
        assert "--initrd" in out

    def test_kernel_hidden_from_lxc_create_help(self, capsys):
        # Mirrors --mac/--qemu-arg: SUPPRESS-ed on the LXC create parser.
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "create", "--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "--kernel" not in out
        assert "--initrd" not in out

    def test_kernel_initrd_pass_through_on_vm(self):
        call = _run_create([
            "vm", "create",
            "--kernel", "/boot/vmlinuz-test",
            "--initrd", "/boot/initramfs-test.img",
            "debian:12"])
        assert call.kwargs["kernel"] == "/boot/vmlinuz-test"
        assert call.kwargs["initramfs"] == "/boot/initramfs-test.img"

    def test_kernel_only_pass_through_on_vm(self):
        # Each side is independent; --initrd absent -> initramfs=None.
        call = _run_create([
            "vm", "create", "--kernel", "/boot/vmlinuz-test", "debian:12"])
        assert call.kwargs["kernel"] == "/boot/vmlinuz-test"
        assert call.kwargs["initramfs"] is None

    def test_initrd_only_pass_through_on_vm(self):
        call = _run_create([
            "vm", "create", "--initrd", "/boot/initramfs-test.img", "debian:12"])
        assert call.kwargs["kernel"] is None
        assert call.kwargs["initramfs"] == "/boot/initramfs-test.img"

    def test_default_none_when_absent_on_vm(self):
        # No override flags -> both None (in-image fallback).
        call = _run_create(["vm", "create", "debian:12"])
        assert call.kwargs["kernel"] is None
        assert call.kwargs["initramfs"] is None

    def test_kernel_rejected_on_lxc_create(self, capsys):
        # Guard must fire BEFORE dispatch: SystemContainer.create (no kernel
        # param) is never reached. Patch BOTH creates and assert neither fired.
        with patch("kento.SystemContainer.create") as msc, \
             patch("kento.VirtualMachine.create") as mvm, \
             pytest.raises(SystemExit) as exc:
            main(["lxc", "create", "--kernel", "/boot/vmlinuz-test", "debian:12"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "--kernel/--initrd are not supported for LXC" in err
        assert not msc.called  # core create NEVER reached (no TypeError path)
        assert not mvm.called

    def test_initrd_rejected_on_lxc_create(self, capsys):
        with patch("kento.SystemContainer.create") as msc, \
             patch("kento.VirtualMachine.create") as mvm, \
             pytest.raises(SystemExit) as exc:
            main(["lxc", "create",
                  "--initrd", "/boot/initramfs-test.img", "debian:12"])
        assert exc.value.code == 1
        assert "--kernel/--initrd are not supported for LXC" in \
            capsys.readouterr().err
        assert not msc.called
        assert not mvm.called

    def test_kernel_rejected_on_lxc_run(self, capsys):
        # `run` shares the create dispatch + parser; same LXC rejection.
        with patch("kento.SystemContainer.create") as msc, \
             patch("kento.VirtualMachine.create") as mvm, \
             pytest.raises(SystemExit) as exc:
            main(["lxc", "run", "--kernel", "/boot/vmlinuz-test", "debian:12"])
        assert exc.value.code == 1
        assert "--kernel/--initrd are not supported for LXC" in \
            capsys.readouterr().err
        assert not msc.called
        assert not mvm.called


# ---------- existing pass-through flags ----------


class TestQemuArgCli:
    """--qemu-arg: exposed on VM scope only, rejected on LXC scope."""

    def test_qemu_arg_in_vm_create_help(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["vm", "create", "--help"])
        assert exc.value.code == 0
        assert "--qemu-arg" in capsys.readouterr().out

    def test_qemu_arg_passes_through_on_vm(self):
        call = _run_create([
            "vm", "create",
            "--qemu-arg", "-device virtio-rng-pci",
            "--qemu-arg", "-smbios type=1,serial=abc",
            "debian:12"])
        assert list(call.kwargs["qemu_args"]) == [
            "-device virtio-rng-pci",
            "-smbios type=1,serial=abc",
        ]

    def test_qemu_arg_default_none_on_vm(self):
        # No --qemu-arg -> the typed create's default empty tuple (no pass-through).
        call = _run_create(["vm", "create", "debian:12"])
        assert tuple(call.kwargs["qemu_args"]) == ()

    def test_qemu_arg_rejected_on_lxc_create(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "create", "--qemu-arg", "-device foo", "debian:12"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "--qemu-arg is not supported for LXC" in err
        assert "--lxc-arg" in err  # pointer to the plain-LXC pass-through flag

    def test_qemu_arg_rejected_on_lxc_run(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "run", "--qemu-arg", "-device foo", "debian:12"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "--qemu-arg is not supported for LXC" in err


class TestLxcArgCli:
    """--lxc-arg: exposed on LXC scope, plain-LXC only."""

    def test_lxc_arg_in_lxc_create_help(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "create", "--help"])
        assert exc.value.code == 0
        assert "--lxc-arg" in capsys.readouterr().out

    def test_lxc_arg_passes_through_on_plain_lxc(self):
        with patch("kento.pve.is_pve", return_value=False):
            call = _run_create([
                "lxc", "create",
                "--lxc-arg", "lxc.cgroup2.devices.allow = c 10:200 rwm",
                "--lxc-arg", "lxc.cap.drop = sys_module",
                "debian:12"])
        assert list(call.kwargs["lxc_args"]) == [
            "lxc.cgroup2.devices.allow = c 10:200 rwm",
            "lxc.cap.drop = sys_module",
        ]

    def test_lxc_arg_default_none(self):
        with patch("kento.pve.is_pve", return_value=False):
            call = _run_create(["lxc", "create", "debian:12"])
        assert tuple(call.kwargs["lxc_args"]) == ()

    def test_lxc_arg_rejected_on_vm_scope(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["vm", "create",
                  "--lxc-arg", "lxc.cap.drop = sys_module", "debian:12"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "--lxc-arg is not applicable to VM modes" in err

    def test_lxc_arg_rejected_on_pve_host(self, capsys):
        """On a PVE host (auto-detect) --lxc-arg redirects to --pve-arg."""
        with pytest.raises(SystemExit) as exc, \
                patch("kento.pve.is_pve", return_value=True):
            main(["lxc", "create",
                  "--lxc-arg", "lxc.cap.drop = sys_module", "debian:12"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "--lxc-arg is not supported on a PVE host" in err
        assert "--pve-arg" in err

    def test_lxc_arg_rejected_on_explicit_pve(self, capsys):
        with pytest.raises(SystemExit) as exc, \
                patch("kento.pve.is_pve", return_value=True):
            main(["lxc", "create", "--pve",
                  "--lxc-arg", "lxc.cap.drop = sys_module", "debian:12"])
        assert exc.value.code == 1
        assert "--lxc-arg is not supported on a PVE host" in \
            capsys.readouterr().err


class TestPveArgCli:
    """--pve-arg: requires a PVE mode (explicit --pve or auto-detected)."""

    def test_pve_arg_in_lxc_create_help(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["lxc", "create", "--help"])
        assert exc.value.code == 0
        assert "--pve-arg" in capsys.readouterr().out

    def test_pve_arg_in_vm_create_help(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["vm", "create", "--help"])
        assert exc.value.code == 0
        assert "--pve-arg" in capsys.readouterr().out

    def test_pve_arg_on_pve_lxc_passes_through(self):
        # --pve-arg rides the typed `extra_args` param (the platform pass-through).
        with patch("kento.pve.is_pve", return_value=True):
            call = _run_create([
                "lxc", "create",
                "--pve", "--pve-arg", "tags: kento-test",
                "--pve-arg", "onboot: 1",
                "debian:12"])
        assert list(call.kwargs["extra_args"]) == [
            "tags: kento-test", "onboot: 1"]

    def test_pve_arg_on_pve_vm_passes_through(self):
        with patch("kento.pve.is_pve", return_value=True):
            call = _run_create([
                "vm", "create", "--pve",
                "--pve-arg", "tags: kento-test", "debian:12"])
        assert list(call.kwargs["extra_args"]) == ["tags: kento-test"]

    def test_pve_arg_on_plain_lxc_rejected(self, capsys):
        """--pve-arg on plain LXC (is_pve() False, auto-detect) errors with
        a pointer to the --lxc-arg flag (the plain-LXC pass-through)."""
        with pytest.raises(SystemExit) as exc, \
                patch("kento.pve.is_pve", return_value=False):
            main(["lxc", "create",
                  "--pve-arg", "tags: foo", "debian:12"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "--pve-arg is not supported for plain LXC" in err
        assert "--lxc-arg" in err

    def test_pve_arg_on_plain_vm_rejected(self, capsys):
        """--pve-arg on plain VM (is_pve() False, auto-detect) errors."""
        with pytest.raises(SystemExit) as exc, \
                patch("kento.pve.is_pve", return_value=False):
            main(["vm", "create",
                  "--pve-arg", "tags: foo", "debian:12"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "--pve-arg is not supported for plain VM" in err

    def test_pve_arg_explicit_no_pve_rejected(self, capsys):
        """Even on a PVE host, --no-pve + --pve-arg is a user error (the
        explicit opt-out branch, separate error message)."""
        with pytest.raises(SystemExit) as exc, \
                patch("kento.pve.is_pve", return_value=True):
            main(["lxc", "create", "--no-pve",
                  "--pve-arg", "tags: foo", "debian:12"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "--pve-arg requires PVE mode" in err
