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

    # create
    p_create = sub.add_parser("create", help="Create container from OCI image")
    p_create.add_argument("name")
    p_create.add_argument("--image", required=True, help="OCI image name")
    p_create.add_argument("--bridge", default=None, help="Network bridge (default: vmbr0 for PVE, lxcbr0 for LXC)")
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
    p_create.add_argument("--vmid", type=int, default=0, help="PVE VMID (auto-assigned if omitted)")

    # destroy
    p_destroy = sub.add_parser("destroy", help="Destroy a container")
    p_destroy.add_argument("name")

    # list
    sub.add_parser("list", help="List kento-managed containers")

    # reset
    p_reset = sub.add_parser("reset", help="Reset container to clean OCI state")
    p_reset.add_argument("name")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "create":
        from kento.create import create
        create(args.name, args.image, bridge=args.bridge, memory=args.memory,
               cores=args.cores, nesting=args.nesting, start=args.start,
               mode=args.mode, vmid=args.vmid)

    elif args.command == "destroy":
        from kento.destroy import destroy
        destroy(args.name)

    elif args.command == "list":
        from kento.list import list_containers
        list_containers()

    elif args.command == "reset":
        from kento.reset import reset
        reset(args.name)
