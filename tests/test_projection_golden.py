"""Golden wire-compat tests for the CLI projection layer (Block 17).

THE wire-compat gate. Each test captures TODAY's exact output from the current
library string-builders (``kento.info.info`` / ``kento.list.list_containers`` /
``kento.diagnose.run_diagnostics`` + ``format_diagnostics``) and asserts the
``kento_cli._projection`` functions reproduce it BYTE-FOR-BYTE from the typed
``Instance`` / ``Diagnosis`` objects loaded from the SAME on-disk state. The
library output IS the golden value — capturing it inline (rather than hand-frozen
strings) keeps the golden anchored to the real wire that ships, so a future
library tweak that would change the bytes fails here too (the contract is "the
projection equals the library", which is what Blocks 18+ rely on).

Representative cases per the brief: list (empty / one-lxc / one-vm / mixed / with
--size); info (lxc / vm / pve / verbose); diagnose (clean / with-problems); both
human AND --json.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest import mock

import pytest

import kento
import kento.info as kinfo
import kento.list as klist
from kento._instances import _load_snapshot
from kento_cli import _projection as proj

_diagnose_mod = importlib.import_module("kento.diagnose")


# --------------------------------------------------------------------------- #
# Builders — minimal on-disk instance dirs (the kento-* state files).
# --------------------------------------------------------------------------- #


def _write(d: Path, name: str, content: str) -> None:
    (d / name).write_text(content)


def _build_lxc(base: Path, cid: str, *, image: str, name: str | None = None,
               mode: str = "lxc", **extra: str) -> Path:
    d = base / cid
    d.mkdir(parents=True)
    _write(d, "kento-image", image + "\n")
    _write(d, "kento-name", (name or cid) + "\n")
    _write(d, "kento-mode", mode + "\n")
    for key, val in extra.items():
        _write(d, key, val)
    return d


@pytest.fixture
def lxc_full(tmp_path):
    """A richly-populated plain-LXC instance dir (every common info field)."""
    return _build_lxc(
        tmp_path / "lxc", "web", image="docker.io/library/debian:bookworm",
        name="web", mode="lxc",
        **{
            "kento-config-mode": "injection\n",
            "kento-port": "10022:22\n",
            "kento-net": "ip=10.0.3.5/24\ngateway=10.0.3.1\ndns=8.8.8.8\nsearchdomain=lan\n",
            "kento-mac": "02:11:22:33:44:55\n",
            "kento-nesting": "1\n",
            "kento-tz": "Europe/Berlin\n",
            "kento-ssh-user": "debian\n",
            "kento-env": "FOO=bar\nBAZ=qux\n",
            "kento-layers": "/var/lib/kento/layers/a:/var/lib/kento/layers/b\n",
            "kento-lxc-args": "lxc.cap.drop = sys_admin\n",
            "kento-memory": "2048\n",
            "kento-cores": "2\n",
        },
    )


@pytest.fixture
def vm_min(tmp_path):
    """A minimal VM instance dir (a stopped vm with a mac + qemu-arg)."""
    return _build_lxc(
        tmp_path / "vm", "builder", image="alpine:3.19", name="builder",
        mode="vm",
        **{
            "kento-mac": "02:aa:bb:cc:dd:ee\n",
            "kento-qemu-args": "-cpu host\n",
        },
    )


# --------------------------------------------------------------------------- #
# Snapshot loader — build a typed Instance from a dir with the runtime probes
# stubbed deterministically (no root, no live containers).
# --------------------------------------------------------------------------- #


def _load(container_dir: Path, mode: str, *, running: bool = False,
          pve_config: bool = True):
    """Load a typed Instance with is_running / pve_config_exists stubbed."""
    with mock.patch("kento.is_running", return_value=running), \
         mock.patch("kento.pve_config_exists", return_value=pve_config):
        return _load_snapshot(container_dir, mode)


def _info_golden(container_dir: Path, name: str, mode: str, *,
                 as_json: bool, verbose: bool, running: bool = False) -> str:
    """The CURRENT library info() output — the golden value."""
    with mock.patch.object(kinfo, "is_running", return_value=running):
        return kinfo.info(name, container_dir=container_dir, mode=mode,
                          as_json=as_json, verbose=verbose)


# --------------------------------------------------------------------------- #
# info / inspect.
# --------------------------------------------------------------------------- #


def test_info_lxc_json_byte_identical(lxc_full):
    golden = _info_golden(lxc_full, "web", "lxc", as_json=True, verbose=False)
    inst = _load(lxc_full, "lxc")
    with mock.patch("kento_cli._projection.is_running", return_value=False):
        out = proj.instance_to_json(inst, verbose=False)
    assert out == golden


def test_info_lxc_human_byte_identical(lxc_full):
    golden = _info_golden(lxc_full, "web", "lxc", as_json=False, verbose=False)
    inst = _load(lxc_full, "lxc")
    with mock.patch("kento_cli._projection.is_running", return_value=False):
        out = proj.instance_to_human(inst, verbose=False)
    assert out == golden


def test_info_vm_json_byte_identical(vm_min):
    golden = _info_golden(vm_min, "builder", "vm", as_json=True, verbose=False)
    inst = _load(vm_min, "vm")
    with mock.patch("kento_cli._projection.is_running", return_value=False):
        out = proj.instance_to_json(inst, verbose=False)
    assert out == golden


def test_info_vm_human_byte_identical(vm_min):
    golden = _info_golden(vm_min, "builder", "vm", as_json=False, verbose=False)
    inst = _load(vm_min, "vm")
    with mock.patch("kento_cli._projection.is_running", return_value=False):
        out = proj.instance_to_human(inst, verbose=False)
    assert out == golden


def test_info_pve_lxc_mode_normalized(tmp_path):
    """A pve (pve-lxc) instance: mode normalizes to 'pve-lxc' in both wires."""
    d = _build_lxc(tmp_path / "lxc", "100", image="debian:bookworm",
                   name="ct", mode="pve")
    golden = _info_golden(d, "ct", "pve", as_json=True, verbose=False)
    inst = _load(d, "pve")
    with mock.patch("kento_cli._projection.is_running", return_value=False):
        out = proj.instance_to_json(inst, verbose=False)
    assert out == golden
    assert '"mode": "pve-lxc"' in out
    assert '"type": "LXC"' in out


def test_info_verbose_layers_and_passthrough(tmp_path):
    """--verbose adds upper_size/layers/layer_sizes + the pass-through section."""
    layer_a = tmp_path / "layers" / "a"
    layer_a.mkdir(parents=True)
    (layer_a / "f").write_text("x" * 100)
    state = tmp_path / "state"
    upper = state / "upper"
    upper.mkdir(parents=True)
    (upper / "g").write_text("y" * 50)
    d = _build_lxc(
        tmp_path / "lxc", "vbose", image="debian:bookworm", name="vbose",
        mode="lxc",
        **{
            "kento-layers": f"{layer_a}\n",
            "kento-state": f"{state}\n",
            "kento-lxc-args": "lxc.cap.drop = sys_admin\n",
        },
    )
    golden_json = _info_golden(d, "vbose", "lxc", as_json=True, verbose=True)
    golden_human = _info_golden(d, "vbose", "lxc", as_json=False, verbose=True)
    inst = _load(d, "lxc")
    with mock.patch("kento_cli._projection.is_running", return_value=False):
        assert proj.instance_to_json(inst, verbose=True) == golden_json
        assert proj.instance_to_human(inst, verbose=True) == golden_human


def test_info_running_status(lxc_full):
    """A running instance projects status 'running' (the is_running probe)."""
    golden = _info_golden(lxc_full, "web", "lxc", as_json=True, verbose=False,
                          running=True)
    inst = _load(lxc_full, "lxc", running=True)
    with mock.patch("kento_cli._projection.is_running", return_value=True):
        out = proj.instance_to_json(inst, verbose=False)
    assert out == golden
    assert '"status": "running"' in out


# --------------------------------------------------------------------------- #
# list / ls.
# --------------------------------------------------------------------------- #


def _list_golden(lxc_base: Path, vm_base: Path, *, as_json: bool,
                 show_size: bool = False, scope=None, running: bool = False,
                 pve_config: bool = True) -> str:
    with mock.patch.object(klist, "LXC_BASE", lxc_base), \
         mock.patch.object(klist, "VM_BASE", vm_base), \
         mock.patch.object(klist, "is_running", return_value=running), \
         mock.patch.object(klist, "pve_config_exists", return_value=pve_config):
        return klist.list_containers(scope=scope, show_size=show_size,
                                     as_json=as_json)


def _load_all(lxc_base: Path, vm_base: Path, *, running: bool = False,
              pve_config: bool = True):
    """Load typed Instances from both base dirs (mirrors Instance.list)."""
    with mock.patch("kento.LXC_BASE", lxc_base), \
         mock.patch("kento.VM_BASE", vm_base), \
         mock.patch("kento.is_running", return_value=running), \
         mock.patch("kento.pve_config_exists", return_value=pve_config):
        return kento.Instance.list()


def test_list_empty_human(tmp_path):
    lxc_base = tmp_path / "lxc"
    vm_base = tmp_path / "vm"
    lxc_base.mkdir()
    vm_base.mkdir()
    golden = _list_golden(lxc_base, vm_base, as_json=False)
    insts = _load_all(lxc_base, vm_base)
    assert proj.instances_to_human(insts) == golden
    assert golden == "(no instances found)"


def test_list_empty_json(tmp_path):
    lxc_base = tmp_path / "lxc"
    vm_base = tmp_path / "vm"
    lxc_base.mkdir()
    vm_base.mkdir()
    golden = _list_golden(lxc_base, vm_base, as_json=True)
    insts = _load_all(lxc_base, vm_base)
    assert proj.instances_to_json(insts) == golden
    assert golden == "[]"


def test_list_one_lxc_human_and_json(tmp_path):
    lxc_base = tmp_path / "lxc"
    vm_base = tmp_path / "vm"
    _build_lxc(lxc_base, "web", image="debian:bookworm", name="web", mode="lxc")
    vm_base.mkdir()
    golden_h = _list_golden(lxc_base, vm_base, as_json=False)
    golden_j = _list_golden(lxc_base, vm_base, as_json=True)
    insts = _load_all(lxc_base, vm_base)
    assert proj.instances_to_human(insts) == golden_h
    assert proj.instances_to_json(insts) == golden_j


def test_list_one_vm_json_has_mac(tmp_path):
    lxc_base = tmp_path / "lxc"
    vm_base = tmp_path / "vm"
    lxc_base.mkdir()
    _build_lxc(vm_base, "builder", image="alpine:3.19", name="builder",
               mode="vm", **{"kento-mac": "02:aa:bb:cc:dd:ee\n"})
    golden_j = _list_golden(lxc_base, vm_base, as_json=True)
    insts = _load_all(lxc_base, vm_base)
    out = proj.instances_to_json(insts)
    assert out == golden_j
    assert '"mac": "02:aa:bb:cc:dd:ee"' in out


def test_list_mixed_human_and_json(tmp_path):
    lxc_base = tmp_path / "lxc"
    vm_base = tmp_path / "vm"
    _build_lxc(lxc_base, "web", image="debian:bookworm", name="web", mode="lxc",
               **{"kento-env": "A=1\n"})
    _build_lxc(vm_base, "builder", image="alpine:3.19", name="builder",
               mode="vm", **{"kento-mac": "02:aa:bb:cc:dd:ee\n"})
    golden_h = _list_golden(lxc_base, vm_base, as_json=False)
    golden_j = _list_golden(lxc_base, vm_base, as_json=True)
    insts = _load_all(lxc_base, vm_base)
    assert proj.instances_to_human(insts) == golden_h
    assert proj.instances_to_json(insts) == golden_j


def test_list_with_size_human_and_json(tmp_path):
    lxc_base = tmp_path / "lxc"
    vm_base = tmp_path / "vm"
    state = tmp_path / "state"
    upper = state / "upper"
    upper.mkdir(parents=True)
    (upper / "g").write_text("z" * 100)
    _build_lxc(lxc_base, "web", image="debian:bookworm", name="web", mode="lxc",
               **{"kento-state": f"{state}\n"})
    vm_base.mkdir()
    golden_h = _list_golden(lxc_base, vm_base, as_json=False, show_size=True)
    golden_j = _list_golden(lxc_base, vm_base, as_json=True, show_size=True)
    insts = _load_all(lxc_base, vm_base)
    assert proj.instances_to_human(insts, show_size=True) == golden_h
    assert proj.instances_to_json(insts, show_size=True) == golden_j


# --------------------------------------------------------------------------- #
# diagnose.
# --------------------------------------------------------------------------- #

# Two synthetic run_diagnostics reports — the wire shape diagnose.py emits.
# The typed Diagnosis is built from these via the library's own mapper, then the
# projection reverses it; the assertion is that the reversed wire == the original.

_CLEAN_REPORT = {
    "checks": [
        {"category": "apparmor", "severity": "ok", "scope": "host",
         "message": "apparmor profile generated OK", "remediation": None},
        {"category": "vmid", "severity": "ok", "scope": "host",
         "message": "no vmid collisions", "remediation": None},
        {"category": "status", "severity": "ok", "scope": "web",
         "message": "running", "remediation": None},
        {"category": "network", "severity": "ok", "scope": "web",
         "message": "eth0 has an address", "remediation": None},
    ],
    "problem_count": 0,
    "instances_scanned": 1,
}

_PROBLEM_REPORT = {
    "checks": [
        {"category": "apparmor", "severity": "ok", "scope": "host",
         "message": "apparmor profile generated OK", "remediation": None},
        {"category": "vmid", "severity": "ok", "scope": "host",
         "message": "no vmid collisions", "remediation": None},
        {"category": "status", "severity": "ok", "scope": "web",
         "message": "running", "remediation": None},
        {"category": "network", "severity": "warn", "scope": "web",
         "message": "no IP on eth0", "remediation": "check the bridge"},
        {"category": "cloudinit", "severity": "info", "scope": "web",
         "message": "cloud-init image", "remediation": None},
        {"category": "mount", "severity": "error", "scope": "db",
         "message": "overlay not mounted", "remediation": "start it"},
    ],
    "problem_count": 2,
    "instances_scanned": 2,
}


def _typed_diagnosis(report: dict):
    """Build the typed Diagnosis the library's mapper produces from a report."""
    from kento._diagnosis import diagnosis_from_report

    return diagnosis_from_report(report)


def test_diagnose_clean_json_round_trips():
    diag = _typed_diagnosis(_CLEAN_REPORT)
    wire = proj.diagnosis_to_wire_dict(diag)
    assert wire == _CLEAN_REPORT


def test_diagnose_problems_json_round_trips():
    diag = _typed_diagnosis(_PROBLEM_REPORT)
    wire = proj.diagnosis_to_wire_dict(diag)
    assert wire == _PROBLEM_REPORT


def test_diagnose_clean_human_byte_identical():
    diag = _typed_diagnosis(_CLEAN_REPORT)
    golden = _diagnose_mod.format_diagnostics(_CLEAN_REPORT)
    assert proj.diagnosis_to_human(diag) == golden


def test_diagnose_problems_human_byte_identical():
    diag = _typed_diagnosis(_PROBLEM_REPORT)
    golden = _diagnose_mod.format_diagnostics(_PROBLEM_REPORT)
    assert proj.diagnosis_to_human(diag) == golden


def test_diagnose_severity_mapping():
    """WARNING -> warn, ERROR -> error, OK/INFO unchanged (the wire vocab)."""
    diag = _typed_diagnosis(_PROBLEM_REPORT)
    wire = proj.diagnosis_to_wire_dict(diag)
    severities = {c["category"]: c["severity"] for c in wire["checks"]}
    assert severities["network"] == "warn"
    assert severities["mount"] == "error"
    assert severities["cloudinit"] == "info"
    assert severities["apparmor"] == "ok"


def test_diagnose_instances_scanned_distinct_instance_subjects():
    """instances_scanned counts distinct INSTANCE-domain subjects (web, db)."""
    diag = _typed_diagnosis(_PROBLEM_REPORT)
    wire = proj.diagnosis_to_wire_dict(diag)
    assert wire["instances_scanned"] == 2
    assert wire["problem_count"] == 2


def test_diagnose_json_string_indented():
    """The --json string matches json.dumps(report, indent=2) exactly."""
    import json

    diag = _typed_diagnosis(_CLEAN_REPORT)
    assert proj.diagnosis_to_json(diag) == json.dumps(_CLEAN_REPORT, indent=2)


def test_diagnose_against_real_run_diagnostics(tmp_path):
    """Round-trip through the GENUINE run_diagnostics, not a synthetic report.

    Anchors the projection to the real wire the library emits: build an instance
    dir, run the actual scan, map to typed via the library mapper, project back,
    and assert the projected wire equals the real report.
    """
    lxc_base = tmp_path / "lxc"
    vm_base = tmp_path / "vm"
    _build_lxc(lxc_base, "web", image="debian:bookworm", name="web", mode="lxc",
               **{"kento-layers": "/nonexistent\n"})
    vm_base.mkdir()
    from kento._diagnosis import diagnosis_from_report

    with mock.patch.object(_diagnose_mod, "LXC_BASE", lxc_base, create=True), \
         mock.patch.object(_diagnose_mod, "VM_BASE", vm_base, create=True), \
         mock.patch.object(kento, "LXC_BASE", lxc_base), \
         mock.patch.object(kento, "VM_BASE", vm_base):
        report = _diagnose_mod.run_diagnostics(None)

    typed = diagnosis_from_report(report)
    wire = proj.diagnosis_to_wire_dict(typed)
    assert wire["checks"] == report["checks"]
    assert wire["problem_count"] == report["problem_count"]
    assert wire["instances_scanned"] == report["instances_scanned"]


# --------------------------------------------------------------------------- #
# Additional byte-exactness edge cases (the brief's gotchas).
# --------------------------------------------------------------------------- #


def test_info_pve_vm_mode_and_vmid(tmp_path):
    """pve-vm: mode stays 'pve-vm', type 'VM', vmid is an int in JSON."""
    d = _build_lxc(tmp_path / "vm", "200", image="alpine:3.19", name="vmpve",
                   mode="pve-vm", **{"kento-vmid": "200\n"})
    golden = _info_golden(d, "vmpve", "pve-vm", as_json=True, verbose=False)
    inst = _load(d, "pve-vm")
    with mock.patch("kento_cli._projection.is_running", return_value=False):
        out = proj.instance_to_json(inst, verbose=False)
    assert out == golden
    assert '"vmid": 200' in out
    assert '"mode": "pve-vm"' in out


def test_info_name_fallback_to_dir(tmp_path):
    """No kento-name file: both info() and the projection fall back to the dir."""
    d = tmp_path / "lxc" / "orphan-id"
    d.mkdir(parents=True)
    (d / "kento-image").write_text("debian:bookworm\n")
    (d / "kento-mode").write_text("lxc\n")
    golden = _info_golden(d, "orphan-id", "lxc", as_json=True, verbose=False)
    inst = _load(d, "lxc")
    with mock.patch("kento_cli._projection.is_running", return_value=False):
        out = proj.instance_to_json(inst, verbose=False)
    assert out == golden


def test_info_multi_port_human_layout(tmp_path):
    """A multi-line kento-port renders the legacy aligned Port: layout."""
    d = _build_lxc(tmp_path / "lxc", "p", image="debian:bookworm", name="p",
                   mode="lxc", **{"kento-port": "10022:22\n8080:80\n"})
    golden = _info_golden(d, "p", "lxc", as_json=False, verbose=False)
    inst = _load(d, "lxc")
    with mock.patch("kento_cli._projection.is_running", return_value=False):
        out = proj.instance_to_human(inst, verbose=False)
    assert out == golden


def test_info_empty_passthrough_lists_present_in_json(lxc_full):
    """qemu_args/pve_args are always present (empty list), lxc_args populated."""
    inst = _load(lxc_full, "lxc")
    with mock.patch("kento_cli._projection.is_running", return_value=False):
        wire = proj.instance_to_wire_dict(inst)
    assert wire["qemu_args"] == []
    assert wire["pve_args"] == []
    assert wire["lxc_args"] == ["lxc.cap.drop = sys_admin"]
