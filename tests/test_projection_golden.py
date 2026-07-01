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
import json
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
# humanizer.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("n,expected", [
    (0, "0B"),
    (1, "1B"),
    (1023, "1023B"),
    (1024, "1.0K"),
    (4096, "4.0K"),
    (1536, "1.5K"),
    (1024 * 1024, "1.0M"),
    (5 * 1024 * 1024, "5.0M"),
    (1024 ** 3, "1.0G"),
    (1024 ** 4, "1.0T"),
])
def test_human_bytes(n, expected):
    assert proj._human_bytes(n) == expected


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


# --------------------------------------------------------------------------- #
# kernel/initramfs boot-source override echo (§8 Phase A, Block A2). The override
# is a CLI-only projection field (core info.py does not render it), so these are
# direct projection assertions, NOT byte-vs-library golden comparisons. Present
# only when the kento-kernel/kento-initramfs markers exist; each side independent.
# --------------------------------------------------------------------------- #


def test_info_kernel_override_present_json_and_human(tmp_path):
    d = _build_lxc(tmp_path / "vm", "ovr", image="alpine:3.19", name="ovr",
                   mode="vm",
                   **{"kento-kernel": "/var/lib/kento/vm/ovr/kernel\n",
                      "kento-initramfs": "/var/lib/kento/vm/ovr/initramfs.img\n"})
    inst = _load(d, "vm")
    with mock.patch("kento_cli._projection.is_running", return_value=False):
        wire = proj.instance_to_wire_dict(inst, verbose=False)
        human = proj.instance_to_human(inst, verbose=False)
    assert wire["kernel"] == "/var/lib/kento/vm/ovr/kernel"
    assert wire["initramfs"] == "/var/lib/kento/vm/ovr/initramfs.img"
    assert "Kernel:     /var/lib/kento/vm/ovr/kernel" in human
    assert "Initramfs:  /var/lib/kento/vm/ovr/initramfs.img" in human


def test_info_kernel_only_override_each_side_independent(tmp_path):
    # --kernel without --initrd: only the kernel key/line is present.
    d = _build_lxc(tmp_path / "vm", "konly", image="alpine:3.19", name="konly",
                   mode="vm",
                   **{"kento-kernel": "/var/lib/kento/vm/konly/kernel\n"})
    inst = _load(d, "vm")
    with mock.patch("kento_cli._projection.is_running", return_value=False):
        wire = proj.instance_to_wire_dict(inst, verbose=False)
        human = proj.instance_to_human(inst, verbose=False)
    assert wire["kernel"] == "/var/lib/kento/vm/konly/kernel"
    assert "initramfs" not in wire
    assert "Kernel:" in human
    assert "Initramfs:" not in human


def test_info_override_absent_omitted_json_and_human(tmp_path):
    # No override markers -> neither key/line appears (present-only-when-set).
    d = _build_lxc(tmp_path / "vm", "noovr", image="alpine:3.19", name="noovr",
                   mode="vm")
    inst = _load(d, "vm")
    with mock.patch("kento_cli._projection.is_running", return_value=False):
        wire = proj.instance_to_wire_dict(inst, verbose=False)
        human = proj.instance_to_human(inst, verbose=False)
    assert "kernel" not in wire
    assert "initramfs" not in wire
    assert "Kernel:" not in human
    assert "Initramfs:" not in human


# --------------------------------------------------------------------------- #
# URL-VM (Phase B, Option 2): a VM instance created from an https:// .txz rootfs
# stores the URL verbatim in kento-image and has NO kento-image-id. The
# projection reads kento-image raw, so the URL renders as-is in the `image`
# field, and the absent kento-image-id (never read by the CLI) does not crash.
# --------------------------------------------------------------------------- #


def test_info_url_image_renders_verbatim(tmp_path):
    url = "https://host/rootfs.txz"
    # A URL-sourced VM: kento-image is the URL; NO kento-image-id written.
    d = _build_lxc(tmp_path / "vm", "urlvm", image=url, name="urlvm", mode="vm")
    assert not (d / "kento-image-id").exists()
    # The projection matches the library byte-for-byte on a URL image too.
    golden = _info_golden(d, "urlvm", "vm", as_json=True, verbose=False)
    inst = _load(d, "vm")
    with mock.patch("kento_cli._projection.is_running", return_value=False):
        wire = proj.instance_to_wire_dict(inst, verbose=False)
        out = proj.instance_to_json(inst, verbose=False)
    assert wire["image"] == url  # URL rendered verbatim, not re-parsed
    assert out == golden


def test_info_url_image_with_url_kernel(tmp_path):
    # A URL rootfs + URL kernel/initrd override: kento-kernel/kento-initramfs
    # hold the URLs verbatim and echo through the CLI-only override projection.
    url = "https://host/rootfs.txz"
    d = _build_lxc(tmp_path / "vm", "urlk", image=url, name="urlk", mode="vm",
                   **{"kento-kernel": "https://h/vmlinuz\n",
                      "kento-initramfs": "https://h/initramfs.img\n"})
    inst = _load(d, "vm")
    with mock.patch("kento_cli._projection.is_running", return_value=False):
        wire = proj.instance_to_wire_dict(inst, verbose=False)
    assert wire["image"] == url
    assert wire["kernel"] == "https://h/vmlinuz"
    assert wire["initramfs"] == "https://h/initramfs.img"


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
    """--verbose adds upper_size/layers/layer_sizes + the pass-through section.

    SD4b: upper_size is now an int (bytes, allocated) from Instance.disk_usage()
    on the --json wire (was a du -sh human string), and the human text humanizes
    it. The legacy library still emits the old string, so this no longer asserts
    byte-equality with the legacy golden for upper_size; layers/layer_sizes and
    the pass-through section are unchanged and DO still match the legacy golden.
    """
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
    inst = _load(d, "lxc")
    with mock.patch("kento_cli._projection.is_running", return_value=False):
        wire = proj.instance_to_wire_dict(inst, verbose=True)
        human = proj.instance_to_human(inst, verbose=True)

    # --json upper_size is an int (bytes), equal to Instance.disk_usage().
    assert isinstance(wire["upper_size"], int)
    assert not isinstance(wire["upper_size"], bool)
    assert wire["upper_size"] == inst.disk_usage()
    assert wire["upper_size"] > 0  # a populated upper

    # layers / layer_sizes are unchanged — still byte-match the legacy golden.
    golden_wire = json.loads(
        _info_golden(d, "vbose", "lxc", as_json=True, verbose=True))
    assert wire["layers"] == golden_wire["layers"]
    assert wire["layer_sizes"] == golden_wire["layer_sizes"]
    assert wire["lxc_args"] == golden_wire["lxc_args"]

    # Human text humanizes the int (NOT the raw int, NOT the legacy du -sh).
    expected = proj._human_bytes(wire["upper_size"])
    assert f"Upper size: {expected}" in human
    assert f"Upper size: {wire['upper_size']}" not in human  # not the raw int
    # The pass-through section still renders verbatim.
    assert "lxc.cap.drop = sys_admin" in human


def test_info_verbose_upper_size_absent_is_zero_int(tmp_path):
    """SD4b presence: with no upper dir, info --verbose --json still emits
    upper_size as int 0 (always-include, stable schema) — the legacy behavior
    OMITTED it; the new contract always includes it."""
    d = _build_lxc(tmp_path / "lxc", "noup", image="debian:bookworm",
                   name="noup", mode="lxc")
    inst = _load(d, "lxc")
    with mock.patch("kento_cli._projection.is_running", return_value=False):
        wire = proj.instance_to_wire_dict(inst, verbose=True)
    assert wire["upper_size"] == 0
    assert isinstance(wire["upper_size"], int)


def test_info_verbose_upper_size_sourced_from_disk_usage(tmp_path):
    """SD4b seam: the CLI sources upper_size from Instance.disk_usage(), not by
    building state_dir/upper + running du/_get_size itself. Stubbing disk_usage
    drives the wire value, proving the CLI no longer does its own accounting."""
    d = _build_lxc(tmp_path / "lxc", "seam", image="debian:bookworm",
                   name="seam", mode="lxc")
    inst = _load(d, "lxc")
    with mock.patch("kento_cli._projection.is_running", return_value=False), \
         mock.patch.object(type(inst), "disk_usage", return_value=4242):
        wire = proj.instance_to_wire_dict(inst, verbose=True)
        human = proj.instance_to_human(inst, verbose=True)
    assert wire["upper_size"] == 4242
    assert f"Upper size: {proj._human_bytes(4242)}" in human


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
        # S4 (Result sweep): Instance.list() returns Result; .unwrap() to the list
        # the projection consumes (mirrors the CLI's _dispatch_list .unwrap()).
        return kento.Instance.list().unwrap()


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
    """SD4b: list --json upper_size is an int (bytes, allocated) from
    Instance.disk_usage(); the human table humanizes it. The legacy library
    still emits the old du -sh string, so this asserts the NEW contract directly
    rather than byte-equality with the legacy golden."""
    lxc_base = tmp_path / "lxc"
    vm_base = tmp_path / "vm"
    state = tmp_path / "state"
    upper = state / "upper"
    upper.mkdir(parents=True)
    (upper / "g").write_text("z" * 100)
    _build_lxc(lxc_base, "web", image="debian:bookworm", name="web", mode="lxc",
               **{"kento-state": f"{state}\n"})
    vm_base.mkdir()
    insts = _load_all(lxc_base, vm_base)
    web = next(i for i in insts if i.name == "web")

    wire = json.loads(proj.instances_to_json(insts, show_size=True))
    entry = next(e for e in wire if e["name"] == "web")
    # --json: int (bytes), equal to disk_usage().
    assert isinstance(entry["upper_size"], int)
    assert not isinstance(entry["upper_size"], bool)
    assert entry["upper_size"] == web.disk_usage()
    assert entry["upper_size"] > 0

    # human table: the humanized string, NOT the raw int.
    human = proj.instances_to_human(insts, show_size=True)
    assert "UPPER SIZE" in human
    assert proj._human_bytes(web.disk_usage()) in human
    assert str(web.disk_usage()) not in human  # not the raw int


def test_list_with_size_json_absent_upper_is_zero_int(tmp_path):
    """SD4b presence: absent upper => upper_size present as int 0 (stable
    machine schema), not omitted, not the string "0"."""
    lxc_base = tmp_path / "lxc"
    vm_base = tmp_path / "vm"
    # No kento-state / no upper dir => disk_usage() returns 0.
    _build_lxc(lxc_base, "web", image="debian:bookworm", name="web", mode="lxc")
    vm_base.mkdir()
    insts = _load_all(lxc_base, vm_base)
    wire = json.loads(proj.instances_to_json(insts, show_size=True))
    entry = next(e for e in wire if e["name"] == "web")
    assert entry["upper_size"] == 0
    assert isinstance(entry["upper_size"], int)
    assert entry["upper_size"] != "0"  # int 0, not the legacy string


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


# A CLEAN STOPPED instance: today's run_diagnostics enumerates ONE instance but
# that instance emits NO INSTANCE-domain finding (only the host apparmor/vmid/hold
# checks fire) — so instances_scanned (=1) is NOT recoverable from the findings.
# This is the case the Editor caught: a finding-derived count would report 0. The
# projection takes instances_scanned as a caller-supplied parameter; the caller
# passes the SAME enumeration count run_diagnostics uses.
_CLEAN_STOPPED_REPORT = {
    "checks": [
        {"category": "apparmor", "severity": "ok", "scope": "host",
         "message": "apparmor profile generated OK", "remediation": None},
        {"category": "vmid", "severity": "ok", "scope": "host",
         "message": "no vmid collisions", "remediation": None},
        {"category": "hold", "severity": "ok", "scope": "host",
         "message": "all holds consistent", "remediation": None},
    ],
    "problem_count": 0,
    "instances_scanned": 1,  # one instance enumerated, zero instance findings
}


def _typed_diagnosis(report: dict):
    """Build the typed Diagnosis the library's mapper produces from a report."""
    from kento._diagnosis import diagnosis_from_report

    return diagnosis_from_report(report)


def _wire(report: dict) -> dict:
    """Project the typed Diagnosis back to wire, passing the REAL scan count.

    The caller (Block 18) supplies instances_scanned = the enumeration count
    run_diagnostics used; the golden report carries that count, so the test
    passes it through exactly as the real handler will.
    """
    diag = _typed_diagnosis(report)
    return proj.diagnosis_to_wire_dict(
        diag, instances_scanned=report["instances_scanned"])


def test_diagnose_clean_json_round_trips():
    assert _wire(_CLEAN_REPORT) == _CLEAN_REPORT


def test_diagnose_problems_json_round_trips():
    assert _wire(_PROBLEM_REPORT) == _PROBLEM_REPORT


def test_diagnose_clean_stopped_instances_scanned_is_caller_count():
    """The Editor's BLOCKER repro + mutation guard.

    A clean STOPPED instance enumerates 1 but emits NO instance-domain finding.
    The wire MUST report instances_scanned == 1 (= len(instances)), NOT 0 (=
    distinct INSTANCE-domain subjects in the findings). This reddens if the
    projection ever reverts to deriving the count from findings.
    """
    wire = _wire(_CLEAN_STOPPED_REPORT)
    assert wire == _CLEAN_STOPPED_REPORT
    assert wire["instances_scanned"] == 1
    # Prove the divergence the parameter fixes: a finding-derived count would be
    # 0 (no INSTANCE-domain subjects), so the caller-supplied 1 is load-bearing.
    from kento import DiagnosisDomain

    diag = _typed_diagnosis(_CLEAN_STOPPED_REPORT)
    derived = len({
        f.subject for f in diag.findings
        if f.domain is DiagnosisDomain.INSTANCE and f.subject is not None
    })
    assert derived == 0
    assert wire["instances_scanned"] != derived


def test_diagnose_clean_human_byte_identical():
    diag = _typed_diagnosis(_CLEAN_REPORT)
    golden = _diagnose_mod.format_diagnostics(_CLEAN_REPORT)
    assert proj.diagnosis_to_human(
        diag, instances_scanned=_CLEAN_REPORT["instances_scanned"]) == golden


def test_diagnose_clean_stopped_human_byte_identical():
    """The human summary header prints instances_scanned — must be the real count."""
    diag = _typed_diagnosis(_CLEAN_STOPPED_REPORT)
    golden = _diagnose_mod.format_diagnostics(_CLEAN_STOPPED_REPORT)
    out = proj.diagnosis_to_human(
        diag, instances_scanned=_CLEAN_STOPPED_REPORT["instances_scanned"])
    assert out == golden
    assert "(1 instance(s) scanned)" in out


def test_diagnose_problems_human_byte_identical():
    diag = _typed_diagnosis(_PROBLEM_REPORT)
    golden = _diagnose_mod.format_diagnostics(_PROBLEM_REPORT)
    assert proj.diagnosis_to_human(
        diag, instances_scanned=_PROBLEM_REPORT["instances_scanned"]) == golden


def test_diagnose_severity_mapping():
    """WARNING -> warn, ERROR -> error, OK/INFO unchanged (the wire vocab)."""
    wire = _wire(_PROBLEM_REPORT)
    severities = {c["category"]: c["severity"] for c in wire["checks"]}
    assert severities["network"] == "warn"
    assert severities["mount"] == "error"
    assert severities["cloudinit"] == "info"
    assert severities["apparmor"] == "ok"


def test_diagnose_problem_count_derived():
    """problem_count = len(problems) (WARNING/ERROR), derived from findings."""
    wire = _wire(_PROBLEM_REPORT)
    assert wire["problem_count"] == 2


def test_diagnose_json_string_indented():
    """The --json string matches json.dumps(report, indent=2) exactly."""
    import json

    diag = _typed_diagnosis(_CLEAN_REPORT)
    out = proj.diagnosis_to_json(
        diag, instances_scanned=_CLEAN_REPORT["instances_scanned"])
    assert out == json.dumps(_CLEAN_REPORT, indent=2)


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
    # Block 18 passes the same enumeration count run_diagnostics used; here we
    # take it straight from the real report (a named/host scan handler would
    # compute it from the instances it enumerated).
    wire = proj.diagnosis_to_wire_dict(
        typed, instances_scanned=report["instances_scanned"])
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


def test_info_created_unknown_on_mtime_oserror(tmp_path):
    """created -> 'unknown' (not a 1969 epoch string) when the mtime probe fails.

    Matches info.py: it re-probes os.path.getmtime live and emits 'unknown' on
    OSError. The typed loader falls back to fromtimestamp(0); the projection must
    NOT strftime that sentinel. We force the OSError on BOTH the library reader
    and the projection so the golden and the projection compare on equal footing
    (the dir stays present so every other field reads normally).
    """
    d = _build_lxc(tmp_path / "lxc", "ghost", image="debian:bookworm",
                   name="ghost", mode="lxc")
    inst = _load(d, "lxc")

    def boom(_path):
        raise OSError("mtime gone")

    with mock.patch("kento.info.os.path.getmtime", boom):
        golden = _info_golden(d, "ghost", "lxc", as_json=True, verbose=False)
    with mock.patch("kento_cli._projection.is_running", return_value=False), \
         mock.patch("kento_cli._projection.os.path.getmtime", boom):
        out = proj.instance_to_json(inst, verbose=False)
    assert out == golden
    assert '"created": "unknown"' in out


def test_info_empty_passthrough_lists_present_in_json(lxc_full):
    """qemu_args/pve_args are always present (empty list), lxc_args populated."""
    inst = _load(lxc_full, "lxc")
    with mock.patch("kento_cli._projection.is_running", return_value=False):
        wire = proj.instance_to_wire_dict(inst)
    assert wire["qemu_args"] == []
    assert wire["pve_args"] == []
    assert wire["lxc_args"] == ["lxc.cap.drop = sys_admin"]
