"""CLI entry point for kento."""

import argparse
import sys

from kento import __version__


def _add_commands(subparser) -> None:
    """Register all subcommands onto a given argparse subparser.

    Called three times: once for top-level, once under 'container', once under 'vm'.
    """
    # create
    p_create = subparser.add_parser("create", help="Create a container from an OCI image")
    p_create.add_argument("image", help="OCI image reference")
    p_create.add_argument("--name", default=None, help="Container name (auto-generated if omitted)")
    p_create.add_argument("--network", default=None,
                          help="Network mode: bridge, bridge=<name>, host, usermode, none")
    p_create.add_argument("--nesting", action=argparse.BooleanOptionalAction, default=True,
                          help="Enable LXC nesting (default: on)")
    p_create.add_argument("--start", action="store_true", help="Start after creation")
    mode_group = p_create.add_mutually_exclusive_group()
    mode_group.add_argument("--pve", action="store_const", const="pve", dest="mode",
                            help="Force PVE mode")
    mode_group.add_argument("--lxc", action="store_const", const="lxc", dest="mode",
                            help="Force plain LXC mode")
    mode_group.add_argument("--vm", action="store_const", const="vm", dest="mode",
                            help="Force VM mode (QEMU + virtiofs)")
    p_create.add_argument("--vmid", type=int, default=0, help="PVE VMID (auto-assigned if omitted)")
    p_create.add_argument("--port", default=None,
                          help="Port forwarding host:guest for VM mode (default: auto-assign)")
    p_create.add_argument("--ip", default=None,
                          help="Static IP address with prefix (e.g. 192.168.0.160/22)")
    p_create.add_argument("--gateway", default=None,
                          help="Default gateway (requires --ip)")
    p_create.add_argument("--dns", default=None,
                          help="DNS server (requires --ip)")
    p_create.add_argument("--searchdomain", default=None,
                          help="DNS search domain")
    p_create.add_argument("--timezone", default=None,
                          help="Timezone (e.g. Europe/Berlin)")
    p_create.add_argument("--env", action="append", default=None,
                          help="Environment variable KEY=VALUE (repeatable)")
    p_create.add_argument("--force", action="store_true",
                          help="Allow creating with a name that exists in the other namespace")

    # start
    p_start = subparser.add_parser("start", help="Start one or more containers")
    p_start.add_argument("name", nargs="+", metavar="CONTAINER", help="Container name(s)")

    # shutdown (with stop as alias)
    p_shutdown = subparser.add_parser("shutdown", help="Gracefully shut down one or more containers")
    p_shutdown.add_argument("name", nargs="+", metavar="CONTAINER", help="Container name(s)")
    p_shutdown.add_argument("-f", "--force", action="store_true",
                            help="Force immediate stop (kill)")

    p_stop = subparser.add_parser("stop", help="Stop one or more containers (alias for shutdown)")
    p_stop.add_argument("name", nargs="+", metavar="CONTAINER", help="Container name(s)")
    p_stop.add_argument("-f", "--force", action="store_true",
                        help="Force immediate stop (kill)")

    # destroy (primary) + rm (alias)
    p_destroy = subparser.add_parser("destroy", help="Remove one or more containers")
    p_destroy.add_argument("name", nargs="+", metavar="CONTAINER", help="Container name(s)")
    p_destroy.add_argument("-f", "--force", action="store_true",
                           help="Force removal of running containers")

    p_rm = subparser.add_parser("rm", help="Remove one or more containers (alias for destroy)")
    p_rm.add_argument("name", nargs="+", metavar="CONTAINER", help="Container name(s)")
    p_rm.add_argument("-f", "--force", action="store_true",
                      help="Force removal of running containers")

    # scrub
    p_scrub = subparser.add_parser("scrub", help="Scrub one or more containers back to clean OCI state")
    p_scrub.add_argument("name", nargs="+", metavar="CONTAINER", help="Container name(s)")

    # list (with ls alias)
    subparser.add_parser("list", help="List containers")
    subparser.add_parser("ls", help="List containers")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="kento",
        description="Compose OCI images into system containers via overlayfs.",
    )
    parser.add_argument("--version", action="version", version=f"kento {__version__}")
    top_sub = parser.add_subparsers(dest="command")

    # -- Top-level bare commands (kento create, kento start, ...) --
    _add_commands(top_sub)

    # -- container subcommand group (kento container create, ...) --
    p_container = top_sub.add_parser("container", help="Manage containers")
    container_sub = p_container.add_subparsers(dest="subcommand")
    _add_commands(container_sub)

    # -- vm subcommand group (kento vm create, ...) --
    p_vm = top_sub.add_parser("vm", help="Manage VMs")
    vm_sub = p_vm.add_subparsers(dest="subcommand")
    _add_commands(vm_sub)

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # Determine scope and effective subcommand
    if args.command in ("container", "vm"):
        scope = args.command
        subcmd = getattr(args, "subcommand", None)
        if subcmd is None:
            (p_container if scope == "container" else p_vm).print_help()
            sys.exit(0)
    else:
        scope = None
        subcmd = args.command
        # For bare commands, subcommand attr may not exist; set it for dispatch
        args.subcommand = subcmd

    _dispatch(args, scope, subcmd)


def _dispatch(args, scope: str | None, subcmd: str) -> None:
    """Dispatch a command with the given scope (None, 'container', or 'vm')."""
    if subcmd == "create":
        _dispatch_create(args, scope)
    elif subcmd in ("start", "shutdown", "stop", "destroy", "rm", "scrub"):
        _dispatch_multi(args, scope, subcmd)
    elif subcmd in ("list", "ls"):
        _dispatch_list(args, scope)


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
        if mode not in ("vm", None):  # None = bare command, might be VM
            print("Error: --network usermode is only supported in VM mode", file=sys.stderr)
            sys.exit(1)
        return "usermode", None
    if network_str == "bridge":
        return "bridge", None  # auto-detect bridge name later
    if network_str.startswith("bridge="):
        bridge_name = network_str.split("=", 1)[1]
        if not bridge_name:
            print("Error: --network bridge=<name> requires a bridge name", file=sys.stderr)
            sys.exit(1)
        return "bridge", bridge_name

    print(f"Error: unknown network mode: {network_str}", file=sys.stderr)
    sys.exit(1)


def _dispatch_create(args, scope: str | None) -> None:
    from kento.create import create

    # Determine the effective mode
    mode = args.mode
    if scope == "vm" and mode is None:
        # kento vm create => force VM mode
        mode = "vm"

    # Name conflict check (only when --name is given and --force is not)
    if args.name and not args.force:
        from kento import check_name_conflict
        target_ns = "vm" if mode == "vm" else "container"
        if check_name_conflict(args.name, target_ns):
            other = "VM" if target_ns == "container" else "container"
            print(
                f"Name '{args.name}' already exists as a {other}. "
                "Use --force to allow duplicate names "
                "(requires explicit 'kento container' or 'kento vm' for all commands).",
                file=sys.stderr,
            )
            sys.exit(1)

    # Parse and validate --network
    net_type, bridge_name = _parse_network(getattr(args, 'network', None), mode)

    # Validate --port + bridge conflict
    if args.port and net_type == "bridge":
        print("Error: --port cannot be used with --network bridge", file=sys.stderr)
        sys.exit(1)

    create(args.image, name=args.name, bridge=bridge_name,
           nesting=args.nesting,
           start=args.start, mode=mode, vmid=args.vmid,
           port=args.port, ip=args.ip, gateway=args.gateway,
           dns=args.dns, searchdomain=args.searchdomain,
           timezone=args.timezone, env=args.env,
           net_type=net_type)


def _dispatch_multi(args, scope: str | None, subcmd: str) -> None:
    errors = 0
    for container_name in args.name:
        try:
            if scope is None:
                from kento import resolve_any
                container_dir, mode = resolve_any(container_name)
            elif scope == "container":
                from kento import resolve_in_namespace
                container_dir = resolve_in_namespace(container_name, "container")
                mode_file = container_dir / "kento-mode"
                mode = mode_file.read_text().strip() if mode_file.is_file() else "lxc"
            else:  # scope == "vm"
                from kento import resolve_in_namespace
                container_dir = resolve_in_namespace(container_name, "vm")
                mode = "vm"

            if subcmd == "start":
                from kento.start import start
                start(container_name)
            elif subcmd in ("shutdown", "stop"):
                from kento.stop import shutdown
                shutdown(container_name, force=args.force)
            elif subcmd in ("destroy", "rm"):
                from kento.destroy import destroy
                destroy(container_name, force=args.force)
            elif subcmd == "scrub":
                from kento.reset import reset
                reset(container_name)
        except SystemExit:
            errors += 1
    if errors:
        sys.exit(1)


def _dispatch_list(args, scope: str | None) -> None:
    from kento.list import list_containers
    list_containers(scope=scope)


if __name__ == "__main__":
    main()
