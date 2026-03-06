"""CLI entry point for kento."""

import argparse
import sys

from kento import __version__


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="kento",
        description="Compose OCI container images into LXC system containers via overlayfs.",
    )
    parser.add_argument("--version", action="version", version=f"kento {__version__}")
    sub = parser.add_subparsers(dest="command")

    # -- container subcommand group --
    p_container = sub.add_parser("container", help="Manage containers")
    container_sub = p_container.add_subparsers(dest="subcommand")

    # container create
    p_create = container_sub.add_parser("create", help="Create container from OCI image")
    p_create.add_argument("image", help="OCI image name")
    p_create.add_argument("--name", default=None, help="Container name (auto-generated if omitted)")
    p_create.add_argument("--bridge", default=None,
                          help="Network bridge (default: vmbr0 for PVE, lxcbr0 for LXC)")
    p_create.add_argument("--memory", type=int, default=0, help="Memory limit in MB (default: no limit)")
    p_create.add_argument("--cores", type=int, default=0, help="CPU cores (default: no limit)")
    p_create.add_argument("--nesting", action=argparse.BooleanOptionalAction, default=True,
                          help="Enable LXC nesting (default: on)")
    p_create.add_argument("--start", action="store_true", help="Start container after creation")
    mode_group = p_create.add_mutually_exclusive_group()
    mode_group.add_argument("--pve", action="store_const", const="pve", dest="mode",
                            help="Force PVE mode")
    mode_group.add_argument("--lxc", action="store_const", const="lxc", dest="mode",
                            help="Force plain LXC mode")
    mode_group.add_argument("--vm", action="store_const", const="vm", dest="mode",
                            help="Force VM mode (QEMU + virtiofs)")
    p_create.add_argument("--vmid", type=int, default=0, help="PVE VMID (auto-assigned if omitted)")
    p_create.add_argument("--port", default=None,
                          help="Port forwarding host:guest (VM mode, default: auto:22)")

    # container start
    p_start = container_sub.add_parser("start", help="Start a container")
    p_start.add_argument("name")

    # container stop
    p_stop = container_sub.add_parser("stop", help="Stop a container")
    p_stop.add_argument("name")

    # container rm
    p_rm = container_sub.add_parser("rm", help="Remove a container")
    p_rm.add_argument("name")

    # container reset
    p_reset = container_sub.add_parser("reset", help="Reset container to clean OCI state")
    p_reset.add_argument("name")

    # container list
    container_sub.add_parser("list", help="List kento-managed containers")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "container":
        if args.subcommand is None:
            p_container.print_help()
            sys.exit(0)
        _dispatch_container(args)


def _dispatch_container(args) -> None:
    if args.subcommand == "create":
        from kento.create import create
        create(args.image, name=args.name, bridge=args.bridge,
               memory=args.memory, cores=args.cores, nesting=args.nesting,
               start=args.start, mode=args.mode, vmid=args.vmid,
               port=args.port)

    elif args.subcommand == "start":
        from kento.start import start
        start(args.name)

    elif args.subcommand == "stop":
        from kento.stop import stop
        stop(args.name)

    elif args.subcommand == "rm":
        from kento.destroy import destroy
        destroy(args.name)

    elif args.subcommand == "list":
        from kento.list import list_containers
        list_containers()

    elif args.subcommand == "reset":
        from kento.reset import reset
        reset(args.name)
