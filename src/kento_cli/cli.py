"""CLI entry point for kento."""

import argparse
import sys

from kento import __version__


def _validate_mac(value: str) -> str:
    """argparse type validator for --mac. Accepts any valid 6-pair hex MAC."""
    from kento.vm import is_valid_mac
    if not is_valid_mac(value):
        raise argparse.ArgumentTypeError(
            f"invalid MAC address: {value!r} (expected XX:XX:XX:XX:XX:XX)"
        )
    return value


def _validate_port(value: str) -> str:
    """argparse type validator for --port.

    Accepts: 'auto' or 'HOST:GUEST' where both are integers in [1, 65535].
    """
    if value == "auto":
        return value
    parts = value.split(":")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"invalid port {value!r}: expected 'HOST:GUEST' (e.g. 10022:22) "
            "or 'auto'"
        )
    try:
        host_port, guest_port = int(parts[0]), int(parts[1])
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid port {value!r}: both sides must be integers"
        )
    for label, p in (("host", host_port), ("guest", guest_port)):
        if not (1 <= p <= 65535):
            raise argparse.ArgumentTypeError(
                f"invalid {label} port {p}: must be in [1, 65535]"
            )
    return value


def _validate_memory(value: str) -> int:
    """argparse type validator for --memory (MB, positive int)."""
    try:
        mb = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid memory {value!r}: must be an integer (MB)"
        )
    if mb < 1:
        raise argparse.ArgumentTypeError(
            f"invalid memory {mb}: must be >= 1 MB"
        )
    return mb


def _validate_cores(value: str) -> int:
    """argparse type validator for --cores (positive int)."""
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid cores {value!r}: must be an integer"
        )
    if n < 1:
        raise argparse.ArgumentTypeError(
            f"invalid cores {n}: must be >= 1"
        )
    return n


def _validate_ip(value: str) -> str:
    """argparse type validator for --ip. Accepts 'A.B.C.D/prefix' form."""
    import ipaddress
    try:
        ipaddress.ip_interface(value)
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError(
            f"invalid IP {value!r}: expected 'A.B.C.D/prefix' "
            "(e.g. 192.168.0.10/24)"
        )
    return value


def _add_create_args(parser, *, scope: str | None = None) -> None:
    """Add the common arguments shared by 'create' and 'run' subcommands.

    When scope == "lxc", the LXC-only `--unconfined` flag is also added.
    """
    parser.add_argument("image", help="OCI image reference")
    parser.add_argument("--name", default=None, help="Instance name (auto-generated if omitted)")
    parser.add_argument("--network", default=None,
                        help="Network mode: bridge, bridge=<name>, host, usermode, none")
    parser.add_argument("--nesting", action=argparse.BooleanOptionalAction, default=True,
                        help="Enable LXC nesting (default: on)")
    if scope == "lxc":
        parser.add_argument("--unconfined", action="store_true", default=False,
                            help="Run container without AppArmor confinement. "
                                 "Required for plain LXC due to systemd 256+ credentials bug.")
    parser.add_argument("--pve", action=argparse.BooleanOptionalAction, default=None,
                        help="Force or prevent PVE integration (default: auto-detect)")
    parser.add_argument("--vmid", type=int, default=0, help="PVE VMID (auto-assigned if omitted)")
    parser.add_argument("--memory", type=_validate_memory, default=None,
                        help="Memory in MB (default: 512 for VM, unset for LXC)")
    parser.add_argument("--cores", type=_validate_cores, default=None,
                        help="Number of CPU cores (default: 1 for VM, unset for LXC)")
    parser.add_argument("--port", default=None, type=_validate_port,
                        help="Port forwarding host:guest (e.g. 10022:22)")
    parser.add_argument("--ip", default=None, type=_validate_ip,
                        help="Static IP address with prefix (e.g. 192.168.0.160/22)")
    parser.add_argument("--gateway", default=None,
                        help="Default gateway (requires --ip)")
    parser.add_argument("--dns", default=None,
                        help="DNS server (requires --ip)")
    parser.add_argument("--searchdomain", default=None,
                        help="DNS search domain")
    parser.add_argument("--timezone", default=None,
                        help="Timezone (e.g. Europe/Berlin)")
    parser.add_argument("--env", action="append", default=None,
                        help="Environment variable KEY=VALUE (repeatable)")
    parser.add_argument("--ssh-key", action="append", default=None,
                        dest="ssh_keys",
                        help="Path to a file with SSH public keys (repeatable)")
    parser.add_argument("--ssh-key-user", default="root",
                        dest="ssh_key_user",
                        help="User whose authorized_keys receives injected SSH keys (default: root)")
    host_key_group = parser.add_mutually_exclusive_group()
    host_key_group.add_argument("--ssh-host-keys", action="store_true",
                                default=False, dest="ssh_host_keys",
                                help="Auto-generate SSH host key pairs at create time")
    host_key_group.add_argument("--ssh-host-key-dir", default=None,
                                dest="ssh_host_key_dir",
                                help="Path to directory with SSH host keys to copy")
    parser.add_argument("--mac", default=None, type=_validate_mac,
                        help="Override the auto-generated MAC address (VM modes only, "
                             "format: XX:XX:XX:XX:XX:XX)")
    parser.add_argument("--config-mode", default="auto",
                        choices=["injection", "cloudinit", "auto"],
                        dest="config_mode",
                        help="Config delivery: injection (file writes), cloudinit (NoCloud seed), auto (detect)")
    parser.add_argument("--force", action="store_true",
                        help="Allow creating with a name that exists in the other namespace")


def _add_commands(subparser, include_create: bool = True,
                  scope: str | None = None) -> None:
    """Register subcommands onto a given argparse subparser.

    When include_create is False, create and run are omitted (for top-level shortcuts).
    `scope` is passed through to `_add_create_args` so LXC-only flags
    (like `--unconfined`) are only registered on `kento lxc create`/`run`.
    """
    if include_create:
        p_create = subparser.add_parser("create", help="Create an instance from an OCI image")
        _add_create_args(p_create, scope=scope)
        p_create.add_argument("--start", action="store_true", help="Start after creation")

        p_run = subparser.add_parser("run", help="Create and start an instance from an OCI image")
        _add_create_args(p_run, scope=scope)

    p_start = subparser.add_parser("start", help="Start one or more instances")
    p_start.add_argument("name", nargs="+", metavar="NAME", help="Instance name(s)")

    p_shutdown = subparser.add_parser("shutdown", help="Gracefully shut down one or more instances")
    p_shutdown.add_argument("name", nargs="+", metavar="NAME", help="Instance name(s)")
    p_shutdown.add_argument("-f", "--force", action="store_true",
                            help="Force immediate stop (kill)")

    p_stop = subparser.add_parser("stop", help="Stop one or more instances (alias for shutdown)")
    p_stop.add_argument("name", nargs="+", metavar="NAME", help="Instance name(s)")
    p_stop.add_argument("-f", "--force", action="store_true",
                        help="Force immediate stop (kill)")

    p_destroy = subparser.add_parser("destroy", help="Remove one or more instances")
    p_destroy.add_argument("name", nargs="+", metavar="NAME", help="Instance name(s)")
    p_destroy.add_argument("-f", "--force", action="store_true",
                           help="Force removal of running instances")

    p_rm = subparser.add_parser("rm", help="Remove one or more instances (alias for destroy)")
    p_rm.add_argument("name", nargs="+", metavar="NAME", help="Instance name(s)")
    p_rm.add_argument("-f", "--force", action="store_true",
                      help="Force removal of running instances")

    p_scrub = subparser.add_parser("scrub", help="Scrub one or more instances back to clean OCI state")
    p_scrub.add_argument("name", nargs="+", metavar="NAME", help="Instance name(s)")

    p_info = subparser.add_parser("info", help="Show instance details")
    p_info.add_argument("name", metavar="NAME", help="Instance name")
    p_info.add_argument("--json", action="store_true", dest="as_json",
                         help="JSON output")
    p_info.add_argument("-v", "--verbose", action="store_true",
                         help="Show layer sizes and paths")

    p_inspect = subparser.add_parser("inspect",
                                      help="Show instance details (alias for info)")
    p_inspect.add_argument("name", metavar="NAME", help="Instance name")
    p_inspect.add_argument("--json", action="store_true", dest="as_json",
                            help="JSON output")
    p_inspect.add_argument("-v", "--verbose", action="store_true",
                            help="Show layer sizes and paths")

    subparser.add_parser("list", help="List instances")
    subparser.add_parser("ls", help="List instances")


def _build_top_help() -> str:
    return """\
usage: kento [--version] [-h] <command>

Compose OCI images into LXC system containers or QEMU VMs via overlayfs.

Commands:
  lxc                 Manage LXC instances
  vm                  Manage VM instances

Shortcuts:
  list, ls            List all instances
  start               Start instances
  stop, shutdown      Stop instances
  destroy, rm         Remove instances
  scrub               Scrub instances to clean OCI state
  info, inspect       Show instance details
  pull                Pull an OCI image

Options:
  --version           Show version and exit
  -h, --help          Show this help message and exit
"""


def _build_lxc_help() -> str:
    return """\
usage: kento lxc [-h] <subcommand>

Manage LXC instances.

Subcommands:
  create              Create an LXC instance from an OCI image
  run                 Create and start an LXC instance
  list, ls            List LXC instances
  start               Start LXC instances
  stop, shutdown      Stop LXC instances
  destroy, rm         Remove LXC instances
  scrub               Scrub LXC instances to clean OCI state
  info, inspect       Show LXC instance details

Options:
  -h, --help          Show this help message and exit
"""


def _build_vm_help() -> str:
    return """\
usage: kento vm [-h] <subcommand>

Manage VM instances.

Subcommands:
  create              Create a VM instance from an OCI image
  run                 Create and start a VM instance
  list, ls            List VM instances
  start               Start VM instances
  stop, shutdown      Stop VM instances
  destroy, rm         Remove VM instances
  scrub               Scrub VM instances to clean OCI state
  info, inspect       Show VM instance details

Options:
  -h, --help          Show this help message and exit
"""


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="kento",
        description="Compose OCI images into LXC system containers or QEMU VMs via overlayfs.",
        add_help=False,
    )
    parser.add_argument("--version", action="version", version=f"kento {__version__}")
    parser.add_argument("-h", "--help", action="store_true", dest="help")
    top_sub = parser.add_subparsers(dest="command")

    # -- Top-level shortcuts (no create/run) --
    _add_commands(top_sub, include_create=False)

    # -- Top-level-only commands (not in lxc/vm subgroups) --
    p_pull = top_sub.add_parser("pull", help="Pull an OCI image")
    p_pull.add_argument("image", help="OCI image reference")

    # -- lxc subcommand group (kento lxc create, ...) --
    p_lxc = top_sub.add_parser("lxc", help="Manage LXC instances")
    p_lxc.format_help = _build_lxc_help
    lxc_sub = p_lxc.add_subparsers(dest="subcommand")
    _add_commands(lxc_sub, scope="lxc")

    # -- vm subcommand group (kento vm create, ...) --
    p_vm = top_sub.add_parser("vm", help="Manage VM instances")
    p_vm.format_help = _build_vm_help
    vm_sub = p_vm.add_subparsers(dest="subcommand")
    _add_commands(vm_sub, scope="vm")

    args = parser.parse_args(argv)

    if getattr(args, "help", False) or args.command is None:
        print(_build_top_help(), end="")
        sys.exit(0)

    # Determine scope and effective subcommand
    if args.command in ("lxc", "vm"):
        scope = args.command
        subcmd = getattr(args, "subcommand", None)
        if subcmd is None:
            if scope == "lxc":
                print(_build_lxc_help(), end="")
            else:
                print(_build_vm_help(), end="")
            sys.exit(0)
    else:
        scope = None
        subcmd = args.command
        args.subcommand = subcmd

    _dispatch(args, scope, subcmd)


def _dispatch(args, scope: str | None, subcmd: str) -> None:
    """Dispatch a command with the given scope (None, 'lxc', or 'vm')."""
    if subcmd == "create":
        _dispatch_create(args, scope)
    elif subcmd == "run":
        args.start = True
        _dispatch_create(args, scope)
    elif subcmd in ("start", "shutdown", "stop", "destroy", "rm", "scrub"):
        _dispatch_multi(args, scope, subcmd)
    elif subcmd in ("info", "inspect"):
        _dispatch_info(args, scope)
    elif subcmd in ("list", "ls"):
        _dispatch_list(args, scope)
    elif subcmd == "pull":
        _dispatch_pull(args)


def _parse_network(network_str: str | None, mode: str | None) -> tuple[str | None, str | None]:
    """Parse --network flag into (net_type, bridge_name).

    Returns (None, None) if no --network was given (auto-detect later).
    """
    if network_str is None:
        return None, None

    if network_str == "none":
        return "none", None
    if network_str == "host":
        if mode == "vm":
            print("Error: --network host is not supported in VM mode", file=sys.stderr)
            sys.exit(1)
        return "host", None
    if network_str == "usermode":
        if mode not in ("vm", None):
            print("Error: --network usermode is only supported in VM mode", file=sys.stderr)
            sys.exit(1)
        return "usermode", None
    if network_str == "bridge":
        return "bridge", None
    if network_str.startswith("bridge="):
        bridge_name = network_str.split("=", 1)[1]
        if not bridge_name:
            print("Error: --network bridge=<name> requires a bridge name", file=sys.stderr)
            sys.exit(1)
        from kento import _bridge_exists
        if not _bridge_exists(bridge_name):
            print(f"Error: bridge {bridge_name!r} does not exist. "
                  f"Check 'ip link show type bridge' or use --network bridge "
                  "to auto-detect.", file=sys.stderr)
            sys.exit(1)
        return "bridge", bridge_name

    print(f"Error: unknown network mode: {network_str}", file=sys.stderr)
    sys.exit(1)


def _dispatch_create(args, scope: str | None) -> None:
    from kento import validate_name
    from kento.create import create

    # Validate explicit --name up front so bad names fail fast, before root
    # check, conflict scan, or any filesystem writes.
    if args.name is not None:
        validate_name(args.name)

    if scope == "lxc":
        mode = "lxc"
    elif scope == "vm":
        mode = "vm"
    else:
        print("Error: specify 'kento lxc create' or 'kento vm create'", file=sys.stderr)
        sys.exit(1)

    # Name conflict check (only when --name is given and --force is not)
    if args.name and not args.force:
        from kento import check_name_conflict
        target_ns = "vm" if mode == "vm" else "lxc"
        if check_name_conflict(args.name, target_ns):
            other = "VM" if target_ns == "lxc" else "LXC"
            print(
                f"Name '{args.name}' already exists as a {other}. "
                "Use --force to allow duplicate names "
                "(requires explicit 'kento lxc' or 'kento vm' for all commands).",
                file=sys.stderr,
            )
            sys.exit(1)

    # Parse and validate --network
    net_type, bridge_name = _parse_network(getattr(args, 'network', None), mode)

    # Validate --port + network combinations (mode-aware)
    if args.port and net_type in ("host", "none"):
        print("Error: --port cannot be used with --network host or --network none",
              file=sys.stderr)
        sys.exit(1)

    # --unconfined is LXC-only; reject with --pve (PVE-LXC uses
    # apparmor.profile=generated which doesn't have the credentials bug).
    unconfined = getattr(args, "unconfined", False)
    if unconfined and args.pve is True:
        print("Error: --unconfined is only for plain LXC; PVE-LXC uses "
              "apparmor.profile=generated which doesn't have this issue.",
              file=sys.stderr)
        sys.exit(1)

    create(args.image, name=args.name, bridge=bridge_name,
           nesting=args.nesting,
           start=args.start, mode=mode, pve=args.pve, vmid=args.vmid,
           memory=args.memory, cores=args.cores,
           port=args.port, ip=args.ip, gateway=args.gateway,
           dns=args.dns, searchdomain=args.searchdomain,
           timezone=args.timezone, env=args.env,
           ssh_keys=args.ssh_keys,
           ssh_key_user=args.ssh_key_user,
           ssh_host_keys=args.ssh_host_keys,
           ssh_host_key_dir=args.ssh_host_key_dir,
           mac=args.mac,
           config_mode=args.config_mode,
           net_type=net_type,
           unconfined=unconfined,
           force=args.force)


def _dispatch_multi(args, scope: str | None, subcmd: str) -> None:
    from kento import validate_name
    errors = 0
    for container_name in args.name:
        try:
            validate_name(container_name)
            if scope is None:
                from kento import resolve_any
                container_dir, mode = resolve_any(container_name)
            elif scope == "lxc":
                from kento import read_mode, resolve_in_namespace
                container_dir = resolve_in_namespace(container_name, "lxc")
                mode = read_mode(container_dir)
            else:  # scope == "vm"
                from kento import resolve_in_namespace
                container_dir = resolve_in_namespace(container_name, "vm")
                mode = "vm"

            if subcmd == "start":
                from kento.start import start
                start(container_name, container_dir=container_dir, mode=mode)
            elif subcmd in ("shutdown", "stop"):
                from kento.stop import shutdown
                shutdown(container_name, force=args.force, container_dir=container_dir, mode=mode)
            elif subcmd in ("destroy", "rm"):
                from kento.destroy import destroy
                destroy(container_name, force=args.force, container_dir=container_dir, mode=mode)
            elif subcmd == "scrub":
                from kento.reset import reset
                reset(container_name, container_dir=container_dir, mode=mode)
        except SystemExit:
            errors += 1
    if errors:
        sys.exit(1)


def _dispatch_info(args, scope: str | None) -> None:
    from kento import require_root, validate_name
    validate_name(args.name)
    require_root()

    if scope is None:
        from kento import resolve_any
        container_dir, mode = resolve_any(args.name)
    elif scope == "lxc":
        from kento import read_mode, resolve_in_namespace
        container_dir = resolve_in_namespace(args.name, "lxc")
        mode = read_mode(container_dir)
    else:  # scope == "vm"
        from kento import read_mode, resolve_in_namespace
        container_dir = resolve_in_namespace(args.name, "vm")
        mode = read_mode(container_dir, "vm")

    from kento.info import info
    info(args.name, container_dir=container_dir, mode=mode,
         as_json=args.as_json, verbose=args.verbose)


def _dispatch_list(args, scope: str | None) -> None:
    from kento.list import list_containers
    list_containers(scope=scope)


def _dispatch_pull(args) -> None:
    from kento import require_root
    require_root()
    import subprocess
    result = subprocess.run(["podman", "pull", args.image])
    if result.returncode != 0:
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
