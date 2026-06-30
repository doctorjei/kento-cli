"""Wire-format projection — typed kento-core objects -> the legacy CLI output.

The library (kento-core) now exposes only TYPED objects: ``Instance.get`` /
``Instance.list`` return ``Instance`` handles, and the ``diagnose`` entry points
return a typed ``Diagnosis``. The legacy ``--json`` wire (a contract seadog
parses) and the human renderings are a **CLI-edge concern** (design §11.8 D1):
this module owns the projection that walks a typed object back into TODAY's exact
bytes, so the command handlers (re-pointed in later blocks) call these functions
instead of the old library string-builders.

Two hard rules govern every function here:

* **Byte-for-byte.** The output must be IDENTICAL to what ``kento.info.info`` /
  ``kento.list.list_containers`` / ``kento.diagnose.run_diagnostics`` +
  ``format_diagnostics`` produce today (pinned by golden fixtures). Key ordering,
  empty-list-vs-absent, ``None``-vs-missing, int-vs-str, and timestamp format all
  matter — seadog reads the ``--json``.
* **No new library surface.** The projection consumes the typed object plus, for
  the residual fields the typed model deliberately does not carry (display-only
  derivations and the raw on-disk strings the wire reproduces verbatim), the
  on-disk ``kento-*`` state read through the public ``Instance.directory``
  property. The existing ``kento.info`` underscore helpers are REUSED for those
  reads so the bytes match the library's own reader exactly — the projection
  reinvents none of that logic.

Field provenance (info --json), as built by :func:`instance_to_wire_dict`:

* from the TYPED object — ``name``, ``mode``/``type`` (class + platform),
  ``vmid`` (``platform_profile.mid``), ``nesting``, ``created`` (datetime ->
  the legacy ``%Y-%m-%d %H:%M:%S`` string), ``mac`` (``network.link_config``),
  ``environment`` (dict -> the ``KEY=VALUE`` line list), the pass-through arg
  lists (``qemu_args``/``pve_args``/``lxc_args``).
* RAW from disk via ``directory`` (byte-faithful where the typed form is lossy) —
  ``image`` (raw ``kento-image``, never re-rendered), ``status`` (the legacy
  ``is_running`` running/stopped probe), ``directory``/``state_directory``,
  ``config_mode``, ``port`` (verbatim string), ``network`` (verbatim
  ``kento-net`` string — the typed ``NetworkConnection`` drops ``searchdomain``
  and decomposes the CIDR, so it cannot reproduce the wire), ``timezone``,
  ``ssh_user``, ``layer_count`` and (verbose) ``layers``/``layer_sizes``/
  ``upper_size``, ``ssh_host_key_fingerprints``.

Spec: ``~/workspace/kento-core-api-design.md`` §11.8 (display projections, D1/D2/
D3) + §1 (``--json`` is a CLI-edge concern; the library is typed objects).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

# REUSE the library's own readers so the projected bytes match the library's
# reader exactly (no reinvented file parsing). These are stable kento.info
# helpers the legacy info()/list() already build the wire from.
from kento import is_running
from kento.info import (
    _get_size,
    _get_ssh_host_key_fingerprints,
    _read_meta,
    _read_passthrough_args,
)

if TYPE_CHECKING:
    from kento import Diagnosis, Instance


# --------------------------------------------------------------------------- #
# Humanizers — int wire value -> human display string (CLI-edge only).
# --------------------------------------------------------------------------- #


def _human_bytes(n: int) -> str:
    """Format a byte count as a short human-readable size for DISPLAY only.

    Used to render the ``upper_size`` int (``Instance.disk_usage()``) in the
    human ``list`` table and ``info`` text block; the raw int stays on the
    ``--json`` wire (same pattern as ``vmid``: machine int, formatted for
    humans). NOT a wire contract — there are no byte-compat fixtures pinning this
    format, so it does not need to byte-match the old ``du -sh`` output; it only
    needs to be a clean, readable size.

    1024-based (binary) units B/K/M/G/T/P, one decimal place above bytes (whole
    bytes for ``< 1K``), e.g. ``0`` -> ``"0B"``, ``4096`` -> ``"4.0K"``,
    ``5242880`` -> ``"5.0M"``. Mirrors the familiar ``du -h`` style.
    """
    if n < 1024:
        return f"{n}B"
    value = float(n)
    for unit in ("K", "M", "G", "T", "P"):
        value /= 1024.0
        if value < 1024.0:
            return f"{value:.1f}{unit}"
    return f"{value:.1f}E"


# --------------------------------------------------------------------------- #
# info / inspect --json — the OBJECT (info.py:88-193 ground truth).
# --------------------------------------------------------------------------- #


def instance_to_wire_dict(inst: "Instance", *, verbose: bool = False) -> dict:
    """Project a typed ``Instance`` to the legacy ``info``/``inspect`` wire dict.

    Reproduces ``kento.info.info(..., as_json=True)`` byte-for-byte (key order
    and all). ``verbose`` adds the ``upper_size`` / ``layers`` / ``layer_sizes``
    keys exactly as the legacy ``--verbose --json`` did.

    The dict is assembled in the SAME insertion order info.py uses so a
    ``json.dumps(..., indent=2)`` of it is identical to today's output.
    """
    container_dir = inst.directory
    data: dict = {}

    # Identity + raw image (raw kento-image string, never re-rendered — the wire
    # guarantee is the stored bytes, and OciReference.render is not guaranteed
    # byte-identical for every legal ref).
    data["name"] = _read_meta(container_dir, "kento-name") or inst.name
    data["image"] = _read_meta(container_dir, "kento-image") or "unknown"

    # mode is the NORMALIZED string (pve -> pve-lxc); type is the LXC/VM family.
    # Both derive from the raw persisted mode, the SAME source info.py reads.
    raw_mode = _raw_mode(inst)
    data["mode"] = _normalize_mode(raw_mode)
    data["type"] = "VM" if raw_mode in ("vm", "pve-vm") else "LXC"

    # status — the LEGACY running/stopped probe. info.py emits ONLY these two
    # (its is_running() bool), never the typed Status's orphan/unknown/suspended.
    data["status"] = "running" if is_running(container_dir, raw_mode) else "stopped"

    data["directory"] = str(container_dir)

    state_text = _read_meta(container_dir, "kento-state")
    state_dir = Path(state_text) if state_text else container_dir
    data["state_directory"] = str(state_dir)

    # Optional metadata — present only when the backing key exists (None-vs-missing
    # matters; an absent key omits the wire field entirely, as info.py does).
    config_mode = _read_meta(container_dir, "kento-config-mode")
    if config_mode:
        data["config_mode"] = config_mode

    vmid = _read_meta(container_dir, "kento-vmid")
    if vmid:
        data["vmid"] = int(vmid)

    port = _read_meta(container_dir, "kento-port")
    if port:
        data["port"] = port

    # network — the RAW kento-net string verbatim (typed NetworkConnection is
    # lossy: drops searchdomain, splits the CIDR, renames keys).
    net = _read_meta(container_dir, "kento-net")
    if net:
        data["network"] = net

    mac = _read_meta(container_dir, "kento-mac")
    if mac:
        data["mac"] = mac

    # kernel/initramfs boot-source override (§8 Phase A) — the in-instance path
    # of a caller-supplied kernel/initramfs, copied in at create time. Present
    # only when overridden (the marker exists); each side independent. Read at
    # the OUTPUT edge via the marker, NOT inst.image() — the override echo is
    # metadata display, not a storage-resolve seam (Instance.image() is the
    # library-API path for programmatic consumers).
    kernel = _read_meta(container_dir, "kento-kernel")
    if kernel:
        data["kernel"] = kernel
    initramfs = _read_meta(container_dir, "kento-initramfs")
    if initramfs:
        data["initramfs"] = initramfs

    nesting = _read_meta(container_dir, "kento-nesting")
    if nesting is not None:
        data["nesting"] = (nesting == "1")

    tz = _read_meta(container_dir, "kento-tz")
    if tz:
        data["timezone"] = tz

    ssh_user = _read_meta(container_dir, "kento-ssh-user") or "root"
    data["ssh_user"] = ssh_user

    env = _read_meta(container_dir, "kento-env")
    if env:
        data["environment"] = env.splitlines()

    # Layers — count from the kento-layers colon-joined paths.
    layers_text = _read_meta(container_dir, "kento-layers")
    if layers_text:
        layer_paths = layers_text.split(":")
        data["layer_count"] = len(layer_paths)
    else:
        layer_paths = []
        data["layer_count"] = 0

    # created — the legacy second-precision mtime string. info.py reads the dir
    # mtime live and emits "unknown" on OSError (the dir vanished mid-read); the
    # typed loader instead falls back to the epoch (fromtimestamp(0)) so the
    # field is always a real datetime. To stay byte-identical to info.py we
    # re-probe the mtime HERE and emit "unknown" on failure, rather than
    # strftime the loader's epoch sentinel (which would print "1969-12-31...").
    try:
        mtime = os.path.getmtime(container_dir)
        data["created"] = datetime.fromtimestamp(mtime).strftime(
            "%Y-%m-%d %H:%M:%S")
    except OSError:
        data["created"] = "unknown"

    # ssh host key fingerprints (always present in JSON; {} when none).
    fingerprints, _has_keys = _get_ssh_host_key_fingerprints(container_dir)
    data["ssh_host_key_fingerprints"] = fingerprints

    # Pass-through flags — always emitted (empty list when absent) for a stable
    # machine schema, matching info.py.
    data["qemu_args"] = _read_passthrough_args(container_dir, "kento-qemu-args")
    data["pve_args"] = _read_passthrough_args(container_dir, "kento-pve-args")
    data["lxc_args"] = _read_passthrough_args(container_dir, "kento-lxc-args")

    if verbose:
        # upper_size — the ALLOCATED byte size of the overlay upperdir, sourced
        # from the typed library (Instance.disk_usage()); the CLI no longer
        # builds the upper path or runs du itself (the Q2 storage-accounting seam
        # is closed). Always emitted as an int (0 when the upper is absent), for
        # a stable machine schema — same precedent as the always-emitted
        # qemu_args/pve_args/lxc_args above. The human renderer humanizes it.
        data["upper_size"] = inst.disk_usage()
        if layer_paths:
            data["layers"] = layer_paths
            sizes = []
            for lp in layer_paths:
                p = Path(lp)
                sizes.append(_get_size(p) if p.is_dir() else None)
            data["layer_sizes"] = sizes

    return data


def instance_to_json(inst: "Instance", *, verbose: bool = False) -> str:
    """The ``info``/``inspect --json`` string — ``json.dumps(..., indent=2)``.

    Matches ``info.info(..., as_json=True)`` exactly (indent=2, no sort_keys —
    insertion order is the wire order).
    """
    return json.dumps(instance_to_wire_dict(inst, verbose=verbose), indent=2)


def instance_to_human(inst: "Instance", *, verbose: bool = False) -> str:
    """The human ``info`` text block, byte-identical to ``info.info(...)``.

    Built from the SAME wire dict ``instance_to_wire_dict`` produces, then
    rendered with the legacy ``_format_human`` line layout (Name:/Image:/...).
    Reusing the dict keeps the two projections in lock-step with one source of
    truth for the field values.
    """
    container_dir = inst.directory
    data = instance_to_wire_dict(inst, verbose=verbose)
    # The human renderer needs the verbose extras populated regardless of the
    # `verbose` flag's effect on the JSON dict; instance_to_wire_dict already
    # gated those on `verbose`, matching info.py (which only adds them in verbose).
    _, has_host_keys = _get_ssh_host_key_fingerprints(container_dir)
    ssh_keygen_missing = has_host_keys and not data.get("ssh_host_key_fingerprints")
    return _format_human(data, verbose, ssh_keygen_missing=ssh_keygen_missing)


def _format_human(data: dict, verbose: bool, *,
                  ssh_keygen_missing: bool = False) -> str:
    """Render the info wire dict as the legacy human block (info.py:_format_human).

    Kept byte-identical to ``kento.info._format_human`` — every label width,
    every conditional line, the SSH-fingerprint ordering, and the verbose
    sections reproduce the library's rendering exactly.
    """
    lines = []
    lines.append(f"Name:       {data['name']}")
    lines.append(f"Image:      {data['image']}")
    lines.append(f"Mode:       {data['mode']} ({data['type']})")
    lines.append(f"Status:     {data['status']}")
    lines.append(f"Created:    {data['created']}")
    lines.append(f"Directory:  {data['directory']}")
    lines.append(f"State:      {data['state_directory']}")

    if "config_mode" in data:
        lines.append(f"Config:     {data['config_mode']}")

    if "vmid" in data:
        lines.append(f"VMID:       {data['vmid']}")
    if "port" in data:
        # kento-port may hold N forward specs (one per line, §5.7A). The JSON
        # wire keeps the raw string verbatim; the human display lists each
        # forward so N lines don't print mangled.
        port_specs = [s for s in str(data["port"]).splitlines() if s.strip()]
        if len(port_specs) <= 1:
            lines.append(f"Port:       {data['port']}")
        else:
            lines.append(f"Port:       {port_specs[0]}")
            for spec in port_specs[1:]:
                lines.append(f"            {spec}")
    if "network" in data:
        lines.append(f"Network:    {data['network']}")
    if "mac" in data:
        lines.append(f"MAC:        {data['mac']}")
    if "kernel" in data:
        lines.append(f"Kernel:     {data['kernel']}")
    if "initramfs" in data:
        lines.append(f"Initramfs:  {data['initramfs']}")
    if "nesting" in data:
        lines.append(f"Nesting:    {'allowed' if data['nesting'] else 'disabled'}")
    if "timezone" in data:
        lines.append(f"Timezone:   {data['timezone']}")
    if data.get("ssh_user", "root") != "root":
        lines.append(f"SSH user:   {data['ssh_user']}")
    if "environment" in data:
        lines.append(f"Env:        {', '.join(data['environment'])}")

    lines.append(f"Layers:     {data['layer_count']}")

    fp = data.get("ssh_host_key_fingerprints", {})
    if fp:
        lines.append("SSH host key fingerprints:")
        # Display order: rsa, ecdsa, ed25519, then any others alphabetically.
        order = ["rsa", "ecdsa", "ed25519"]
        ordered_keys = [k for k in order if k in fp]
        ordered_keys += sorted(k for k in fp if k not in order)
        for kt in ordered_keys:
            label = kt.upper()
            lines.append(f"  {label + ':':<10} {fp[kt]}")
    elif ssh_keygen_missing:
        lines.append("SSH host key fingerprints:")
        lines.append("  ssh-keygen not found, cannot display fingerprints")

    if verbose:
        if "upper_size" in data:
            # data["upper_size"] is the raw int (bytes) that reaches --json;
            # humanize it for the text block (same pattern as vmid: int on the
            # wire, formatted for humans).
            lines.append(f"Upper size: {_human_bytes(data['upper_size'])}")
        if "layers" in data:
            lines.append("Layer paths:")
            layer_sizes = data.get("layer_sizes", [])
            for i, lp in enumerate(data["layers"]):
                size = layer_sizes[i] if i < len(layer_sizes) else None
                if size is None:
                    size = "missing"
                lines.append(f"  [{i}] {lp} ({size})")

        qemu_args = data.get("qemu_args", [])
        pve_args = data.get("pve_args", [])
        lxc_args = data.get("lxc_args", [])
        if qemu_args or pve_args or lxc_args:
            lines.append("Pass-through flags:")
            if qemu_args:
                lines.append("  --qemu-arg:")
                for line in qemu_args:
                    lines.append(f"    {line}")
            if pve_args:
                lines.append("  --pve-arg:")
                for line in pve_args:
                    lines.append(f"    {line}")
            if lxc_args:
                lines.append("  --lxc-arg:")
                for line in lxc_args:
                    lines.append(f"    {line}")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# list --json + human table — the ARRAY (list.py:79-156 ground truth).
# --------------------------------------------------------------------------- #


def _instance_to_list_entry(inst: "Instance", *, as_json: bool,
                            show_size: bool) -> dict:
    """One ``list`` row, mirroring list.py's per-entry dict assembly.

    The base keys (name/type/mode/image/status) always; the mac/env/vmid/
    fingerprint extras ONLY when ``as_json`` (the human table never shows them,
    and the fingerprint read shells out per key — skipped on the columnar path).
    ``upper_size`` is added when ``show_size``.
    """
    container_dir = inst.directory
    container_id = container_dir.name

    display_name = _read_meta(container_dir, "kento-name") or container_id
    image = _read_meta(container_dir, "kento-image") or ""
    raw_mode = _raw_mode(inst)
    ctype = _normalize_mode(raw_mode)
    family = "VM" if raw_mode in ("vm", "pve-vm") else "LXC"

    # status — list.py surfaces ORPHAN for PVE modes (config gone); the typed
    # Status resolver computes exactly that (ORPHAN/RUNNING/STOPPED/UNKNOWN). The
    # wire value is the Status enum's string, which equals list.py's strings for
    # the cases list emits (running/stopped/orphan). UNKNOWN never arose in the
    # legacy is_running path, but the Status enum value "unknown" is the faithful
    # projection of an unobservable instance (it cannot regress a real case).
    status = inst.status.value

    entry: dict = {
        "name": display_name,
        "type": family,
        "mode": ctype,
        "image": image,
        "status": status,
    }

    if as_json:
        vmid = _read_meta(container_dir, "kento-vmid")
        if vmid is not None:
            try:
                entry["vmid"] = int(vmid)
            except (TypeError, ValueError):
                entry["vmid"] = vmid

        mac = _read_meta(container_dir, "kento-mac")
        if mac:
            entry["mac"] = mac

        env_raw = _read_meta(container_dir, "kento-env")
        if env_raw:
            env_lines = env_raw.splitlines()
            if env_lines:
                entry["environment"] = env_lines

        fingerprints, _ = _get_ssh_host_key_fingerprints(container_dir)
        if fingerprints:
            entry["ssh_host_key_fingerprints"] = fingerprints

    if show_size:
        # upper_size — the ALLOCATED byte size of the overlay upperdir, sourced
        # from the typed library (Instance.disk_usage()); the CLI no longer
        # builds the upper path or runs du itself (the Q2 storage-accounting seam
        # is closed). Always an int (0 when the upper is absent), matching list's
        # prior always-emit behavior (it emitted "0" before) and giving --json a
        # stable machine schema. The human table humanizes it.
        entry["upper_size"] = inst.disk_usage()

    return entry


def instances_to_wire_list(insts: "list[Instance]", *,
                           show_size: bool = False) -> list[dict]:
    """Project typed ``Instance`` handles to the legacy ``list --json`` array.

    Mirrors ``list.py``'s ordering (by container-dir name) and per-entry shape.
    The caller passes the instances it wants listed (the scope filter is the
    caller's; ``Instance.list()`` already scans both namespaces). Each entry is
    the full ``as_json`` shape.
    """
    ordered = sorted(insts, key=lambda i: i.directory.name)
    return [
        _instance_to_list_entry(i, as_json=True, show_size=show_size)
        for i in ordered
    ]


def instances_to_json(insts: "list[Instance]", *,
                      show_size: bool = False) -> str:
    """The ``list --json`` string — ``json.dumps(array, indent=2)``.

    Byte-identical to ``list.list_containers(as_json=True)`` (indent=2, insertion
    order). An empty list renders as ``[]`` exactly as the library does.
    """
    return json.dumps(instances_to_wire_list(insts, show_size=show_size),
                      indent=2)


def instances_to_human(insts: "list[Instance]", *,
                       show_size: bool = False) -> str:
    """The human ``list`` table, byte-identical to ``list.list_containers(...)``.

    Reproduces the column widths, the ``-`` rule row, the ``  `` (two-space)
    separator, the trailing column padding, and the ``(no instances found)``
    sentinel — exactly as list.py renders them.
    """
    ordered = sorted(insts, key=lambda i: i.directory.name)
    entries = [
        _instance_to_list_entry(i, as_json=False, show_size=show_size)
        for i in ordered
    ]

    if not entries:
        return "(no instances found)"

    if show_size:
        # entry["upper_size"] is the raw int (bytes) that reaches --json;
        # humanize it for the table column (the int stays on the wire only).
        rows = [(e["name"], e["mode"], e["image"], e["status"],
                 _human_bytes(e["upper_size"]))
                for e in entries]
        headers = ("NAME", "TYPE", "IMAGE", "STATUS", "UPPER SIZE")
    else:
        rows = [(e["name"], e["mode"], e["image"], e["status"])
                for e in entries]
        headers = ("NAME", "TYPE", "IMAGE", "STATUS")

    widths = []
    for i, header in enumerate(headers):
        col_max = max((len(row[i]) for row in rows), default=0)
        widths.append(max(len(header), col_max))

    lines = ["  ".join(h.ljust(w) for h, w in zip(headers, widths)),
             "  ".join("-" * w for w in widths)]
    for row in rows:
        lines.append("  ".join(val.ljust(w) for val, w in zip(row, widths)))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# diagnose --json + human — the OBJECT (diagnose.py:502-617 ground truth).
#
# The library's typed Diagnosis (kento._diagnosis) is the clean DOMAIN model; the
# wire format is the legacy flat dict seadog parses. This projection reverses the
# library's `diagnosis_from_report` mapping (§11.8 D3): check->category,
# WARNING->warn (others identity), subject->scope (None->"host"), and derives the
# `problem_count` / `instances_scanned` stats the typed model deliberately omits.
# --------------------------------------------------------------------------- #


# CheckLevel (library word) -> severity (wire word). Only WARNING differs from
# its enum value ("warning" -> wire "warn"); every other level's enum value IS
# the wire string. The inverse of kento._diagnosis._SEVERITY_TO_LEVEL.
_LEVEL_TO_SEVERITY = {
    "ok": "ok",
    "info": "info",
    "warning": "warn",
    "error": "error",
}


def _finding_to_wire(finding) -> dict:
    """One typed ``Finding`` -> the legacy flat wire finding dict.

    Keys in the legacy order: category, severity, scope, message, remediation.
    ``check`` -> ``category`` (verbatim — the library kept the runtime word);
    ``level`` -> ``severity`` (WARNING->warn); ``subject`` -> ``scope``
    (``None`` -> the literal ``"host"``, reversing the host-finding rule);
    ``message`` verbatim; ``remediation`` verbatim (``None`` stays ``None`` ->
    JSON ``null``, as the runtime emits).
    """
    return {
        "category": finding.check,
        "severity": _LEVEL_TO_SEVERITY.get(finding.level.value, finding.level.value),
        "scope": "host" if finding.subject is None else finding.subject,
        "message": finding.message,
        "remediation": finding.remediation,
    }


def diagnosis_to_wire_dict(diag: "Diagnosis", *, instances_scanned: int) -> dict:
    """Project a typed ``Diagnosis`` to the legacy ``diagnose --json`` wire dict.

    Reproduces ``run_diagnostics``'s return shape (diagnose.py:546-550):
    ``{"checks": [...], "problem_count": int, "instances_scanned": int}``.

    * ``checks`` — every finding projected via :func:`_finding_to_wire`, in the
      diagnosis's finding order (the typed model preserves it).
    * ``problem_count`` — ``len(diag.problems)`` (WARNING/ERROR findings); the
      same count the runtime derives (``severity in (warn, error)``).
    * ``instances_scanned`` — **caller-supplied**, NOT derived from the findings.

    Why ``instances_scanned`` is a parameter and not derived: today's
    ``run_diagnostics`` sets ``instances_scanned = len(enumerated instances)``
    (diagnose.py:549) — the count of instances the scan *visited*, which is NOT
    recoverable from the findings. A clean STOPPED instance can emit no
    INSTANCE-domain finding at all (only the host apparmor/hold checks fire), so
    a finding-derived count would report 0 where the real wire reports 1 — and
    seadog reads this field. The §11.8 "coverage derivable from findings" model
    assumes a future one-OK-finding-per-subject scan that ``run_diagnostics``
    does NOT do today; until that diagnose-polish pass lands, the only
    wire-faithful source is the enumeration count the caller already has.

    The caller (Block 18's diagnose handler) passes the SAME count
    ``run_diagnostics`` uses — e.g. the number of enumerated instance dirs /
    ``len(Instance.list())`` for a host-wide scan, ``1`` for a named-instance
    scan — so the projected wire matches byte-for-byte.
    """
    checks = [_finding_to_wire(f) for f in diag.findings]
    problem_count = len(diag.problems)

    return {
        "checks": checks,
        "problem_count": problem_count,
        "instances_scanned": instances_scanned,
    }


def diagnosis_to_json(diag: "Diagnosis", *, instances_scanned: int) -> str:
    """The ``diagnose --json`` string — ``json.dumps(..., indent=2)``.

    Byte-identical to the legacy ``json.dumps(report, indent=2)`` the CLI emits
    today (insertion order; ``remediation: null`` for ``None``).
    ``instances_scanned`` is caller-supplied (see :func:`diagnosis_to_wire_dict`).
    """
    return json.dumps(
        diagnosis_to_wire_dict(diag, instances_scanned=instances_scanned),
        indent=2,
    )


def diagnosis_to_human(diag: "Diagnosis", *, instances_scanned: int) -> str:
    """The human ``diagnose`` block, byte-identical to ``format_diagnostics``.

    Delegates to the library's ``format_diagnostics`` against the projected wire
    dict — the human renderer is pure string formatting over the wire shape, so
    reusing it (rather than re-implementing the grouping/summary layout) keeps
    the bytes exact with one source of truth. The summary header itself prints
    ``instances_scanned`` (``"... (N instance(s) scanned)."``), so it must be the
    real caller-supplied count too (see :func:`diagnosis_to_wire_dict`).
    ``format_diagnostics`` is reached via the ``kento.diagnose`` SUBMODULE (NOT
    ``from kento import diagnose``, which resolves to the shadowing module-level
    function — the documented foot-gun).
    """
    import importlib

    diagnose_mod = importlib.import_module("kento.diagnose")
    return diagnose_mod.format_diagnostics(
        diagnosis_to_wire_dict(diag, instances_scanned=instances_scanned)
    )


# --------------------------------------------------------------------------- #
# images — format the typed ImageRecord ledger (SD3 / §12.4 / §11.8 D2).
#
# `kento images` is human-only (no --json contract — nothing scrapes it, D2
# upheld), so this is a CLI-edge human projection over the typed
# kento.ImageRecord.list() — NO library string crosses the seam (the former
# images.list_images() was removed). The output is improved over the old table
# (it is NOT byte-bound, Jei run 36): an ID column surfaces the content identity
# the ledger is keyed on, and a dangling (no-tag) image is shown explicitly
# rather than printing an empty IMAGE cell.
# --------------------------------------------------------------------------- #


def _short_id(digest) -> str:
    """A short, human-scannable form of a content ``Digest`` (12 hex chars).

    Mirrors podman's short-id convention. ``digest`` is a typed ``kento.Digest``
    (``algorithm`` + ``encoded``); we show the leading 12 chars of ``encoded``.
    """
    return digest.encoded[:12]


def images_to_human(records: "list") -> str:
    """Render ``kento.ImageRecord.list()`` as the human ``kento images`` table.

    ``records`` is a ``list[kento.ImageRecord]`` (typed — classes-only seam).
    Columns: IMAGE (the tag(s) kento has seen at the id, comma-joined; or
    ``<dangling>`` when the image carries no surviving tag), ID (short content
    id — the ledger key), GUESTS (referencing instances, or ``-``), HOLD
    (``yes``/``no``), STATUS (``in-use``/``orphaned`` — the typed
    ``ManagedStatus`` value). Empty set => the same "No kento-managed images."
    line the legacy table emitted.
    """
    if not records:
        return "No kento-managed images."

    rows = []
    for rec in records:
        image_cell = ",".join(r.render() for r in rec.refs) if rec.refs \
            else "<dangling>"
        guests_cell = ",".join(rec.guests) if rec.guests else "-"
        hold_cell = "yes" if rec.held else "no"
        # rec.status is a ManagedStatus (str, Enum) — its value is the wire
        # string ("in-use"/"orphaned"); str() yields exactly that.
        rows.append((
            image_cell,
            _short_id(rec.id),
            guests_cell,
            hold_cell,
            rec.status.value,
        ))

    headers = ("IMAGE", "ID", "GUESTS", "HOLD", "STATUS")
    widths = []
    for i, header in enumerate(headers):
        col_max = max((len(row[i]) for row in rows), default=0)
        widths.append(max(len(header), col_max))

    lines = []
    lines.append("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append("  ".join(val.ljust(w) for val, w in zip(row, widths)))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Small shared helpers.
# --------------------------------------------------------------------------- #


def _raw_mode(inst: "Instance") -> str:
    """The RAW persisted kento-mode ("lxc"/"pve"/"vm"/"pve-vm") for ``inst``.

    Read from the instance directory via the runtime's own ``read_mode`` — the
    SAME source info.py / list.py use (so the family + normalization derive from
    identical bytes). The typed object splits the flat mode across class +
    platform_profile, so we read the flat string back at the boundary rather than
    re-deriving it (which would risk a mapping seam).
    """
    from kento import read_mode

    return read_mode(inst.directory)


def _normalize_mode(raw_mode: str) -> str:
    """Normalize the raw mode for the wire: bare ``pve`` -> ``pve-lxc``.

    The SAME normalization info.py / list.py apply so ``info --json`` and
    ``list --json`` agree on the mode string. Every other mode passes through
    unchanged (lxc / vm / pve-vm).
    """
    return "pve-lxc" if raw_mode == "pve" else raw_mode
