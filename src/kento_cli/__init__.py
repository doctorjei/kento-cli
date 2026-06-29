"""CLI entry point for kento."""

import argparse
import logging
import sys
from importlib.metadata import version as _dist_version

from kento.errors import KentoError, SubprocessError

try:
    # Report the CLI's OWN version (the `kento` dist), not the library's. The
    # two diverge during the cooking phase: `kento` is a stable release while
    # `kento-core` rides `.devN` pre-releases (see design §6). Reading the
    # library's __version__ here would make a stable CLI mis-report as a .dev.
    __version__ = _dist_version("kento")
except Exception:  # running from a raw checkout, not an installed dist
    __version__ = "unknown"


def _exit_code(exc: KentoError) -> int:
    """Map a library exception to the process exit code, preserving the
    monolith's contract: a missing/unexecutable external tool is 2, every
    other KentoError is 1. (SubprocessError carries returncode=None when the
    tool could not be launched at all — see kento.subprocess_util.run_or_die.)
    """
    if isinstance(exc, SubprocessError) and exc.returncode is None:
        return 2
    return 1


def _handle(fn):
    """Run fn(); on KentoError print 'Error: <msg>' to stderr and exit with the
    mapped code. The CLI is the ONLY place exceptions become exit codes. Any
    return value of fn is passed through untouched on success."""
    try:
        return fn()
    except KentoError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(_exit_code(exc))


class _MaxLevelFilter(logging.Filter):
    """Pass only records strictly below `level` (so INFO goes to stdout while
    WARNING+ is left for the stderr handler)."""
    def __init__(self, level: int):
        super().__init__()
        self._level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < self._level


class _DynamicStreamHandler(logging.StreamHandler):
    """StreamHandler that looks up sys.stdout or sys.stderr on every emit so
    pytest's capsys fd-replacement is always honoured."""

    def __init__(self, stream_name: str):
        # Pass None; we override self.stream below on every emit.
        super().__init__(None)
        self._stream_name = stream_name

    @property
    def stream(self):
        return getattr(sys, self._stream_name)

    @stream.setter
    def stream(self, value):
        # logging.StreamHandler.__init__ assigns self.stream during construction
        # (None becomes sys.stderr). Ignore it: the getter is the single source of
        # truth, resolving sys.<name> live on every emit so capsys / a redirected
        # sys.stdout|stderr always wins.
        pass


def _configure_logging() -> None:
    """Attach handlers to the 'kento' library logger so progress is visible.

    INFO (progress + success) -> stdout; WARNING/ERROR (degraded) -> stderr.
    Bare '%(message)s' format — the monolith printed plain lines with no level
    prefix. Idempotent: a sentinel attr prevents duplicate handlers when main()
    is re-entered in tests."""
    log = logging.getLogger("kento")
    if getattr(log, "_kento_cli_configured", False):
        return
    log.setLevel(logging.INFO)

    fmt = logging.Formatter("%(message)s")

    out = _DynamicStreamHandler("stdout")
    out.setLevel(logging.INFO)
    out.addFilter(_MaxLevelFilter(logging.WARNING))
    out.setFormatter(fmt)

    err = _DynamicStreamHandler("stderr")
    err.setLevel(logging.WARNING)
    err.setFormatter(fmt)

    log.addHandler(out)
    log.addHandler(err)
    log._kento_cli_configured = True


def _validate_mac(value: str) -> str:
    """argparse type validator for --mac. Accepts unicast MACs; rejects multicast."""
    from kento.vm import is_valid_mac
    if not is_valid_mac(value):
        raise argparse.ArgumentTypeError(
            f"invalid MAC address: {value!r} (expected XX:XX:XX:XX:XX:XX)"
        )
    # F16: reject multicast (first-octet LSB set) and broadcast MACs.
    # A NIC assigned a multicast MAC will silently drop its own unicast
    # traffic on most stacks, so this is always a user error.
    first_octet = int(value.split(":")[0], 16)
    if first_octet & 0x01:
        raise argparse.ArgumentTypeError(
            f"invalid MAC address: {value!r} is multicast/broadcast "
            f"(first-octet LSB is set). Use a unicast MAC — "
            f"locally-administered MACs (second-LSB set, e.g. 02/06/0a/0e) "
            f"are fine."
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


def _validate_timeout(value: str) -> int:
    """argparse type validator for --timeout (seconds, positive int)."""
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid timeout {value!r}: must be an integer (seconds)"
        )
    if n < 1:
        raise argparse.ArgumentTypeError(
            f"invalid timeout {n}: must be >= 1"
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


def _validate_ip_or_dhcp(value: str) -> str:
    """argparse validator for `set --ip`: a CIDR address, or 'dhcp' to clear."""
    if value == "dhcp":
        return value
    return _validate_ip(value)


def _add_create_args(parser, *, scope: str | None = None) -> None:
    """Add the common arguments shared by 'create' and 'run' subcommands."""
    parser.add_argument("image", help="OCI image reference")
    parser.add_argument("--name", default=None, help="Instance name (auto-generated if omitted)")
    parser.add_argument("--network", default=None,
                        help="Network mode: bridge, bridge=<name>, host, usermode, none")
    parser.add_argument("--allow-nesting", action=argparse.BooleanOptionalAction,
                        default=False, dest="allow_nesting",
                        help="Allow nested virtualization/containerization. "
                             "LXC modes: the container may run nested containers. "
                             "VM modes: the guest is exposed CPU virtualization "
                             "extensions (vmx/svm) so it can run hardware-accelerated "
                             "VMs. Default: off.")
    parser.add_argument("--unprivileged", action="store_true",
                        default=False, dest="unprivileged",
                        help="Create an unprivileged LXC container (plain-lxc "
                             "and pve-lxc; rejected for VM modes). Maps "
                             "container root to an unprivileged host UID/GID "
                             "range via per-layer idmapped overlay mounts. "
                             "Requires kernel >= 5.19 and util-linux >= 2.40; "
                             "fails closed with a clear error otherwise.")
    parser.add_argument("--pve", action=argparse.BooleanOptionalAction, default=None,
                        help="Force or prevent PVE integration (default: auto-detect)")
    parser.add_argument("--vmid", type=int, default=0, help="PVE VMID (auto-assigned if omitted)")
    parser.add_argument("--memory", type=_validate_memory, default=None,
                        help="Memory in MB (default: 1024 for VM, unset for LXC)")
    parser.add_argument("--cores", type=_validate_cores, default=None,
                        help="Number of CPU cores (default: 1 for VM, unset for LXC)")
    parser.add_argument("--port", action="append", default=None,
                        type=_validate_port,
                        help="Port forwarding host:guest (e.g. 10022:22). "
                             "Repeatable for multiple forwards.")
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
                        help="User whose authorized_keys receives injected SSH keys (default: root); "
                             "cloud images usually need a distro user like 'debian' rather than root")
    host_key_group = parser.add_mutually_exclusive_group()
    host_key_group.add_argument("--ssh-host-keys", action="store_true",
                                default=False, dest="ssh_host_keys",
                                help="Auto-generate SSH host key pairs at create time")
    host_key_group.add_argument("--ssh-host-key-dir", default=None,
                                dest="ssh_host_key_dir",
                                help="Path to directory with SSH host keys to copy")
    parser.add_argument("--mac", default=None, type=_validate_mac,
                        help=(argparse.SUPPRESS if scope == "lxc" else
                              "Override the auto-generated MAC address (VM modes only, "
                              "format: XX:XX:XX:XX:XX:XX)"))
    parser.add_argument("--config-mode", default="auto",
                        choices=["injection", "cloudinit", "auto"],
                        dest="config_mode",
                        help="Config delivery: injection (file writes), cloudinit (NoCloud seed), auto (detect)")
    parser.add_argument("--qemu-arg", action="append", default=None,
                        dest="qemu_args", metavar="ARG",
                        help=(argparse.SUPPRESS if scope == "lxc" else
                              "Extra QEMU argument appended verbatim to the VM's argv "
                              "(VM modes only, repeatable). Stored in "
                              "<instance_dir>/kento-qemu-args, one per line."))
    parser.add_argument("--pve-arg", action="append", default=None,
                        dest="pve_args", metavar="KEY: VALUE",
                        help="Extra line appended verbatim to the generated PVE config "
                             "(PVE modes only, repeatable). Stored in "
                             "<instance_dir>/kento-pve-args, one line per entry.")
    parser.add_argument("--lxc-arg", action="append", default=None,
                        dest="lxc_args", metavar="KEY = VALUE",
                        help=(argparse.SUPPRESS if scope == "vm" else
                              "Append a raw line to the plain-LXC native config "
                              "(plain LXC only, repeatable). Stored in "
                              "<instance_dir>/kento-lxc-args, one line per entry."))
    parser.add_argument("--force", action="store_true",
                        help="Allow creating with a name that exists in the other namespace")


def _add_commands(subparser, include_create: bool = True,
                  scope: str | None = None) -> None:
    """Register subcommands onto a given argparse subparser.

    When include_create is False, create and run are omitted (for top-level shortcuts).
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
    p_shutdown.add_argument("--timeout", type=_validate_timeout, default=None,
                            help="Graceful shutdown window in seconds before hard-stop "
                                 "fallback (pve-vm only, default: 30)")
    p_shutdown.add_argument("--graceful-only", action="store_true",
                            dest="graceful_only",
                            help="Drop the hard-stop fallback; wait forever for "
                                 "graceful shutdown (pve-vm only)")

    p_stop = subparser.add_parser("stop", help="Stop one or more instances (alias for shutdown)")
    p_stop.add_argument("name", nargs="+", metavar="NAME", help="Instance name(s)")
    p_stop.add_argument("-f", "--force", action="store_true",
                        help="Force immediate stop (kill)")
    p_stop.add_argument("--timeout", type=_validate_timeout, default=None,
                        help="Graceful shutdown window in seconds before hard-stop "
                             "fallback (pve-vm only, default: 30)")
    p_stop.add_argument("--graceful-only", action="store_true",
                        dest="graceful_only",
                        help="Drop the hard-stop fallback; wait forever for "
                             "graceful shutdown (pve-vm only)")

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

    p_attach = subparser.add_parser("attach",
                                    help="Attach to an instance's console (interactive)")
    p_attach.add_argument("name", metavar="NAME", help="Instance name")

    p_enter = subparser.add_parser("enter",
                                   help="Attach to an instance's console (alias for attach)")
    p_enter.add_argument("name", metavar="NAME", help="Instance name")

    p_exec = subparser.add_parser("exec",
                                  help="Run a command inside an instance (LXC/PVE-LXC only)")
    p_exec.add_argument("name", metavar="NAME", help="Instance name")
    p_exec.add_argument("exec_command", nargs=argparse.REMAINDER,
                        metavar="COMMAND",
                        help="Command to run (use '--' before flags, "
                             "e.g. 'kento exec NAME -- ls -la')")

    p_logs = subparser.add_parser("logs",
                                  help="Show journalctl logs from an instance (LXC/PVE-LXC only)")
    p_logs.add_argument("name", metavar="NAME", help="Instance name")
    p_logs.add_argument("args", nargs=argparse.REMAINDER, metavar="ARGS",
                        help="Extra args forwarded to journalctl (e.g. -f -n 50)")

    p_set = subparser.add_parser(
        "set",
        help="Change scalar settings on a stopped instance (takes effect next start)")
    p_set.add_argument("name", metavar="NAME", help="Instance name")
    p_set.add_argument("--memory", type=int, default=None, dest="memory",
                       metavar="MB", help="Memory limit in MB")
    p_set.add_argument("--cores", type=int, default=None, dest="cores",
                       metavar="N", help="Number of CPU cores")
    p_set.add_argument("--mac", default=None, dest="mac", metavar="MAC",
                       type=_validate_mac,
                       help="MAC address (VM modes only, XX:XX:XX:XX:XX:XX)")
    p_set.add_argument("--qemu-arg", action="append", default=None,
                       dest="qemu_args", metavar="ARG",
                       help="Replace the QEMU pass-through list (VM modes only, "
                            "repeatable). Pass --qemu-arg '' to clear.")
    p_set.add_argument("--pve-arg", action="append", default=None,
                       dest="pve_args", metavar="KEY: VALUE",
                       help="Replace the PVE config pass-through list (PVE modes "
                            "only, repeatable). Pass --pve-arg '' to clear.")
    p_set.add_argument("--lxc-arg", action="append", default=None,
                       dest="lxc_args", metavar="KEY = VALUE",
                       help="Replace the plain-LXC native config pass-through "
                            "list (plain LXC only, repeatable). Pass "
                            "--lxc-arg '' to clear.")
    p_set.add_argument("--network", default=None, dest="network",
                       help="Network mode: bridge, bridge=<name>, host, "
                            "usermode, none")
    p_set.add_argument("--ip", default=None, dest="ip",
                       type=_validate_ip_or_dhcp,
                       help="Static IP with prefix (e.g. 192.168.0.10/24), or "
                            "'dhcp' to clear the static address "
                            "(requires bridge networking)")
    p_set.add_argument("--gateway", default=None, dest="gateway",
                       help="Default gateway (requires a static --ip)")
    p_set.add_argument("--dns", default=None, dest="dns",
                       help="DNS server")
    p_set.add_argument("--hostname", default=None, dest="hostname",
                       help="Instance hostname")
    p_set.add_argument("--port", action="append", default=None, dest="port",
                       metavar="HOST:GUEST",
                       help="Port forwarding HOST:GUEST (usermode VM or bridge "
                            "LXC/PVE). Pass --port '' to clear.")

    p_suspend = subparser.add_parser(
        "suspend",
        help="Pause a running VM's vCPUs (VM modes only)")
    p_suspend.add_argument("name", metavar="NAME", help="Instance name")

    p_resume = subparser.add_parser(
        "resume",
        help="Resume a suspended VM's vCPUs (VM modes only)")
    p_resume.add_argument("name", metavar="NAME", help="Instance name")

    p_list = subparser.add_parser("list", help="List instances")
    p_list.add_argument("-s", "--size", action="store_true", dest="show_size",
                        help="Include the UPPER SIZE column (runs 'du -sh' per "
                             "instance; slow on long-running containers).")
    p_list.add_argument("--json", action="store_true", dest="as_json",
                        help="JSON output")
    p_ls = subparser.add_parser("ls", help="List instances")
    p_ls.add_argument("-s", "--size", action="store_true", dest="show_size",
                      help="Include the UPPER SIZE column (runs 'du -sh' per "
                           "instance; slow on long-running containers).")
    p_ls.add_argument("--json", action="store_true", dest="as_json",
                      help="JSON output")


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
  attach, enter       Attach to an instance's console (interactive)
  exec                Run a command inside an instance (LXC/PVE-LXC)
  logs                Show journalctl logs from an instance (LXC/PVE-LXC)
  suspend             Pause a running VM's vCPUs (VM modes only)
  resume              Resume a suspended VM's vCPUs (VM modes only)
  pull                Pull an OCI image
  images              List kento-managed OCI images
  prune               Remove orphaned hold containers and freed images
                      (--orphans also reaps orphaned instance state)
  diagnose            Read-only health scan of instances and the host
  adopt               Adopt an orphaned PVE instance (regenerate its config)

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
  attach, enter       Attach to an LXC instance's console (interactive)
  exec                Run a command inside an LXC instance
  logs                Show journalctl logs from an LXC instance
  suspend             Unsupported for LXC (use 'kento stop')
  resume              Unsupported for LXC (use 'kento start')

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
  attach, enter       Attach to a VM instance's console (interactive)
  exec                Run a command inside an instance (LXC/PVE-LXC only)
  logs                Show journalctl logs (LXC/PVE-LXC only)
  suspend             Pause a running VM's vCPUs
  resume              Resume a suspended VM's vCPUs

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

    p_images = top_sub.add_parser("images", help="List kento-managed OCI images")
    p_images.add_argument("--in-use", action="store_true", dest="in_use",
                          help="Show only images referenced by an existing guest")

    p_prune = top_sub.add_parser(
        "prune",
        help="Remove orphaned kento hold containers and freed images "
             "(--orphans also reaps orphaned instance state)")
    p_prune.add_argument("--yes", action="store_true",
                         help="Actually remove (default: dry-run)")
    p_prune.add_argument("--orphans", action="store_true",
                         help="Also discard orphaned PVE instance state "
                              "(state dir survives but the PVE config is gone)")

    p_diagnose = top_sub.add_parser(
        "diagnose",
        help="Run a read-only health scan of kento instances and the host")
    p_diagnose.add_argument("name", nargs="?", default=None, metavar="NAME",
                            help="Scope checks to one instance (host-level "
                                 "checks still run); omit for a host-wide scan")
    p_diagnose.add_argument("--json", action="store_true", dest="as_json",
                            help="Emit the raw report as JSON")

    p_adopt = top_sub.add_parser(
        "adopt",
        help="Adopt an orphaned PVE instance by regenerating its missing "
             "PVE config from surviving kento state")
    p_adopt.add_argument("name", metavar="NAME",
                         help="Name of the orphaned PVE instance to adopt")

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

    _configure_logging()
    _handle(lambda: _dispatch(args, scope, subcmd))


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
    elif subcmd in ("attach", "enter"):
        _dispatch_attach(args, scope)
    elif subcmd == "exec":
        _dispatch_exec(args, scope)
    elif subcmd == "logs":
        _dispatch_logs(args, scope)
    elif subcmd == "set":
        _dispatch_set(args, scope)
    elif subcmd == "suspend":
        _dispatch_suspend(args, scope)
    elif subcmd == "resume":
        _dispatch_resume(args, scope)
    elif subcmd in ("list", "ls"):
        _dispatch_list(args, scope)
    elif subcmd == "pull":
        _dispatch_pull(args)
    elif subcmd == "images":
        # Re-pointed (SD3, JC1) onto the typed managed-image ledger
        # kento.ImageRecord.list() — the LAST classes-only seam for `images`.
        # The library no longer renders the table as a string (list_images() was
        # removed); the CLI formats the typed records here (images_to_human). NO
        # library string crosses the seam, and NO --json (D2 upheld — `images`
        # is human-only). The --in-use filter is preserved by FILTERING the typed
        # list CLI-side (record.in_use), the M21 pattern. Output is improved over
        # the old table (an ID column + an explicit <dangling> cell — `images` is
        # not byte-bound, Jei run 36).
        import kento

        from kento_cli._projection import images_to_human

        records = kento.ImageRecord.list()
        if args.in_use:
            records = [r for r in records if r.in_use]
        print(images_to_human(records))
    elif subcmd == "prune":
        import kento
        from kento import PruneScope

        kento.require_root()
        # Re-pointed (Phase 6) onto the typed reclaim ops (plan §Phase 6 map,
        # behavior-policy Q1 — surface the library's cleaner semantics as an
        # intentional, CHANGELOG'd delta). Both ops return the shared typed
        # ReclaimReport (M25, a frozen dataclass — classes-only seam, no dict).
        #
        # ** BEHAVIOR DELTA (CHANGELOG'd) ** Bare `kento prune` now reclaims
        # podman DANGLING images (Image.prune, M22) — untagged <none> layers
        # podman no longer references, never a held image. This REPLACES the
        # former kento orphan-HOLD GC (removing kento-hold.<guest> containers of
        # vanished guests + the images they freed): the hold-GC has no typed
        # home in 1.0 (Image.prune is dangling-GC; Instance.prune_orphans is
        # PVE-instance-orphan GC — both distinct from hold-GC). `--orphans`
        # below is unchanged in intent.
        # Spec §11.5 phrases M19-M23 as `Image.*`, but the abstract `Image` base
        # (and the abstract `LayeredImage` layering node) are genuine ABCs; the
        # as-built classmethods (pull/list/prune) live on the concrete `OciImage`
        # (the only 1.0 OCI representation — disclosed placement). Use it directly.
        report = kento.OciImage.prune(scope=PruneScope.DANGLING)
        print(_format_image_prune(report))
        failed = bool(report.failed)
        if args.orphans:
            # --orphans: batch-reconcile orphaned PVE instance state (M4).
            # reap=args.yes -> dry-run unless --yes (the ReclaimReport's dry_run
            # mirrors that). Heavier blast radius (discards instance state), so
            # it stays a separately sectioned, opt-in pass.
            orphans = kento.Instance.prune_orphans(reap=args.yes)
            print()
            print(_format_orphan_prune(orphans))
            failed = failed or bool(orphans.failed)
        # Exit non-zero after BOTH sections print, so all output shows. A
        # surfaced failure (held/externally-referenced image, or a failed reap)
        # is meaningful — mirror today's exit-1-on-failure contract.
        if failed:
            sys.exit(1)
    elif subcmd == "diagnose":
        _dispatch_diagnose(args)
    elif subcmd == "adopt":
        import kento

        kento.require_root()
        # M3: Instance.adopt heals the orphan and returns a typed handle (a
        # SystemContainer / VirtualMachine). CLASSES-ONLY: the CLI formats the
        # success line from the handle's public properties — name and the PVE
        # vmid (platform_profile.mid; always present on an adopted PVE instance,
        # since adopt is pve-lxc/pve-vm only and fails closed otherwise).
        inst = kento.Instance.adopt(args.name)
        print(f"adopted '{inst.name}' (vmid {inst.platform_profile.mid}); "
              f"run 'kento start {inst.name}'")


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

    # --mac only affects VM modes (see create.py: kento-mac is written only
    # for mode in ('vm', 'pve-vm')). Silently accepting it for LXC misleads
    # users who expect it to stick. PVE-LXC mode is reached via lxc scope +
    # --pve auto-promotion; reject at both branches.
    if scope == "lxc" and args.mac is not None:
        print("Error: --mac is not supported for LXC/PVE-LXC; it applies only "
              "to VM modes. Remove --mac or use 'kento vm create'.",
              file=sys.stderr)
        sys.exit(1)

    # --qemu-arg only applies to VM modes (plain VM and PVE-VM both boot
    # QEMU; LXC modes never invoke QEMU). Reject at the LXC scope with a
    # pointer to --pve-arg (PVE-LXC) / --lxc-arg (plain LXC) which serve the
    # escape-hatch role for the LXC config surfaces.
    if scope == "lxc" and getattr(args, "qemu_args", None):
        print("Error: --qemu-arg is not supported for LXC/PVE-LXC; it applies "
              "only to VM modes. For PVE-LXC config pass-through use "
              "--pve-arg; for plain-LXC native config pass-through use "
              "--lxc-arg.", file=sys.stderr)
        sys.exit(1)

    # --lxc-arg targets plain-LXC's native config ONLY. On a PVE host (or
    # explicit --pve) the LXC config is the PVE .conf, which already carries
    # raw lxc.* lines via --pve-arg; VM scope has no native LXC config.
    # Mirror the pve_args scope check, inverted.
    if scope == "vm" and getattr(args, "lxc_args", None):
        print("Error: --lxc-arg is not applicable to VM modes (no native LXC "
              "config). For QEMU pass-through use --qemu-arg.", file=sys.stderr)
        sys.exit(1)
    if scope == "lxc" and getattr(args, "lxc_args", None):
        from kento.pve import is_pve
        if args.pve is True or (args.pve is None and is_pve()):
            print("Error: --lxc-arg is not supported on a PVE host. On PVE "
                  "the LXC config is the PVE config; use --pve-arg, which "
                  "carries raw lxc.* lines.", file=sys.stderr)
            sys.exit(1)

    # --pve-arg requires a PVE mode — either explicit --pve, or PVE
    # auto-detected on this host. Plain LXC has a different config surface
    # (a .conf file, not k/v) and plain VM has no PVE qm config to append to.
    if getattr(args, "pve_args", None):
        from kento.pve import is_pve
        if args.pve is False:
            print("Error: --pve-arg requires PVE mode but --no-pve was specified.",
                  file=sys.stderr)
            sys.exit(1)
        if args.pve is None and not is_pve():
            if scope == "lxc":
                print("Error: --pve-arg is not supported for plain LXC; it "
                      "appends lines to the PVE qm/lxc config and only applies "
                      "on PVE hosts. For plain-LXC native config pass-through "
                      "use --lxc-arg. Drop --pve-arg or run on a PVE host "
                      "with --pve.", file=sys.stderr)
            else:
                print("Error: --pve-arg is not supported for plain VM; it "
                      "appends lines to the PVE qm config and only applies "
                      "on PVE hosts. Drop --pve-arg or run on a PVE host "
                      "with --pve.", file=sys.stderr)
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

    # Re-pointed onto the typed M15/M16 create (Phase 6, CLASSES-ONLY seam):
    # decompose the flat flags into the typed parameter objects the typed
    # `SystemContainer.create` / `VirtualMachine.create` take, then call it. The
    # CLI-level pre-checks above (scope/mode validity, name conflict, port-vs-
    # network) are unchanged — they fail fast before any library call.
    from kento import (
        SystemContainer,
        VirtualMachine,
        parse_forwards,
    )

    # --network/--ip/--gateway/--dns/--mac -> a NetworkConnection (or None to let
    # create.py auto-detect, preserving today's no---network behavior).
    network = _build_create_network(
        net_type, bridge_name, args.ip, args.gateway, args.dns, args.mac)

    # --memory/--cores -> the typed resources bag (only the keys provided).
    resources: dict[str, int] = {}
    if args.memory is not None:
        resources["memory"] = args.memory
    if args.cores is not None:
        resources["cores"] = args.cores

    # --env KEY=VALUE -> the typed environment map (create.py validates each).
    environment = _env_list_to_map(args.env)

    # --port (repeatable) -> the typed forwards map (declarative). The typed
    # create renders it back to create.py's port spec list (§5.7).
    forwards = parse_forwards(list(args.port)) if args.port else None

    # --pve (tri-state) + --vmid -> a PlatformProfile (or None = auto-detect).
    platform, mid = _pve_to_platform(args.pve, args.vmid)

    kind = VirtualMachine if mode == "vm" else SystemContainer
    common = dict(
        hostname=getattr(args, "hostname", None),
        platform=platform,
        mid=mid,
        network=network,
        forwards=forwards,
        resources=resources or None,
        environment=environment,
        start=args.start,
        nesting=args.allow_nesting,
        extra_args=getattr(args, "pve_args", None) or (),
        searchdomain=args.searchdomain,
        timezone=args.timezone,
        ssh_keys=args.ssh_keys,
        ssh_key_user=args.ssh_key_user,
        ssh_host_keys=args.ssh_host_keys,
        ssh_host_key_dir=args.ssh_host_key_dir,
        config_mode=args.config_mode,
        force=args.force,
    )
    if mode == "vm":
        # --unprivileged applies to LXC modes only. The typed
        # `VirtualMachine.create` deliberately has no `unprivileged` param (VMs
        # have their own isolation), so the flag would otherwise be silently
        # ignored here. Reject at the CLI edge to restore the pre-re-point hard
        # error (matches the legacy create.py ModeError; covers vm + pve-vm,
        # both of which reach this branch via vm scope). _handle maps the
        # ModeError to "Error: ..." + exit 1.
        if args.unprivileged:
            from kento.errors import ModeError
            raise ModeError(
                "--unprivileged applies to LXC modes only (VMs have their "
                "own isolation)."
            )
        kind.create(args.name, args.image,
                    qemu_args=getattr(args, "qemu_args", None) or (),
                    **common)
    else:
        kind.create(args.name, args.image,
                    unprivileged=args.unprivileged,
                    lxc_args=getattr(args, "lxc_args", None) or (), **common)


def _build_create_network(net_type, bridge_name, ip, gateway, dns, mac):
    """Build a ``NetworkConnection`` from the flat create flags (§5.1) or None.

    Returns ``None`` when NO network-affecting flag was given, so the typed
    create passes nothing and ``create.py`` AUTO-DETECTS (bridge for LXC,
    usermode for plain VM) — preserving today's no-``--network`` behavior.
    Otherwise maps the parsed ``net_type`` (``bridge``/``host``/``usermode``/
    ``none`` or ``None``) + the L2/L3 flags onto the typed value:

    * ``host``/``usermode``/``none`` -> the matching mode (no L3).
    * ``bridge`` or (L3 flags with no ``--network``) -> STATIC if a static
      ``--ip`` is present, else DHCP. A bare ``--ip``/``--gateway``/``--dns``
      with no ``--network`` resolves to bridge networking (matching create.py's
      auto-detect, which picks a bridge when L3 is requested); the typed create
      then auto-detects the bridge NAME when none is given.
    """
    from kento import NetworkConnection, NetworkMode, parse_cidr

    if net_type is None and ip is None and gateway is None and dns is None \
            and mac is None:
        return None

    link_config: dict[str, str] = {}
    if bridge_name:
        link_config["bridge"] = bridge_name
    if mac is not None:
        link_config["mac"] = mac

    if net_type == "host":
        mode = NetworkMode.HOST
    elif net_type == "usermode":
        mode = NetworkMode.USER
    elif net_type == "none":
        mode = NetworkMode.DISABLED
    else:
        # "bridge", or L3 flags with no explicit --network -> bridge family.
        ip_config: dict[str, str] = {}
        if ip is not None:
            address, subnet = parse_cidr(ip)
            ip_config["address"] = address
            if subnet is not None:
                ip_config["subnet"] = subnet
        if gateway is not None:
            ip_config["gateway"] = gateway
        if dns is not None:
            ip_config["dns1"] = dns
        mode = NetworkMode.STATIC if ip_config.get("address") else NetworkMode.DHCP
        return NetworkConnection(
            mode=mode, link_config=link_config, ip_config=ip_config)

    return NetworkConnection(mode=mode, link_config=link_config)


def _pve_to_platform(pve, vmid):
    """Map ``--pve`` (tri-state) + ``--vmid`` onto ``(platform, mid)`` for the
    typed create (§6, §11.4).

    The typed create takes a ``platform`` (PVE intent) + a separate ``mid``
    (vmid; ``None`` = auto-allocate). A ``PlatformProfile`` is an IDENTITY value,
    so a ``PVE`` profile REQUIRES a concrete ``mid`` (>= 100, §6.2) — but at
    CREATE time the vmid may be auto-allocated (``--vmid`` omitted -> 0). The
    mapping:

    * ``--no-pve`` (``pve is False``) -> ``(PlatformProfile(STANDARD), None)``
      (force non-PVE).
    * ``--pve --vmid N`` (N given)     -> ``(PlatformProfile(PVE, mid=N), None)``
      (force PVE at a chosen vmid — the profile carries the id).
    * ``--pve`` with auto-vmid         -> ``(PlatformProfile(PVE-intent), None)``
      via the floor sentinel below — we CANNOT build a valid PVE identity
      profile without a vmid, so the PVE force + auto-vmid rides ``platform=None``
      + relies on PVE auto-detection.  **Disclosed nuance (Phase-6 re-point):**
      ``--pve`` WITHOUT ``--vmid`` no longer hard-forces PVE independently of the
      host — on a PVE host it behaves identically (auto-detect -> PVE); the only
      lost case is forcing a PVE-specific error on a NON-PVE host when no vmid is
      given (an edge that create's later mode checks still catch). Pass ``--vmid``
      to force PVE explicitly.
    * no flag (``pve is None``)        -> ``(None, mid)`` (auto-detect — today's
      default).

    Returns ``(platform, mid)`` where ``mid`` is the create ``mid`` param
    (``None`` = auto-allocate).
    """
    from kento import PlatformMode, PlatformProfile

    mid = vmid if vmid else None
    if pve is False:
        return PlatformProfile(mode=PlatformMode.STANDARD, mid=None,
                               extra_args=()), mid
    if pve is True and mid is not None:
        # Force PVE at a chosen vmid: the profile carries the id (mid -> None to
        # avoid the conflict guard; the profile.mid supplies the vmid).
        return PlatformProfile(mode=PlatformMode.PVE, mid=mid,
                               extra_args=()), None
    # --pve with auto-vmid, or no --pve flag: auto-detect (platform=None). On a
    # PVE host this yields PVE; mid (None) auto-allocates the vmid.
    return None, mid


def _env_list_to_map(env_list):
    """Turn the CLI's ``--env KEY=VALUE`` list into the typed environment map.

    ``create.py`` validates each entry (missing ``=`` / bad key / embedded
    newline) — but the typed create takes a ``dict[str, str]``, so we split here
    at the boundary. A malformed entry (no ``=``) is a clear ``ValidationError``
    rather than a silent drop (§2 principle 5). ``None``/empty -> ``None``.
    """
    if not env_list:
        return None
    from kento.errors import ValidationError

    env: dict[str, str] = {}
    for entry in env_list:
        key, sep, value = entry.partition("=")
        if not sep or not key:
            raise ValidationError(
                f"invalid --env entry {entry!r}; expected KEY=VALUE."
            )
        env[key] = value
    return env


def _dispatch_multi(args, scope: str | None, subcmd: str) -> None:
    """Re-pointed start/stop/shutdown/destroy/rm/scrub onto Instance.* (Phase 6).

    Each name is resolved to its typed handle via the polymorphic ``get`` entry
    point (the same scope->class mapping ``info``/``list`` use, §10.1), then the
    matching lifecycle method (M5 ``start`` / M6 ``stop`` / M7 ``destroy`` / M8
    ``scrub``) is called. Per-name errors are isolated and counted exactly as
    before — one bad name does not abort the rest; any failure makes the process
    exit 1 (the legacy ``errors`` accumulator contract).

    Behavior deltas surfaced here (banked-Jei policy — CHANGELOG'd):

    * **stop (M6)** — the typed ``stop`` redesign is the deliberate improvement.
      Plain ``stop`` (no flags) and ``--graceful-only`` BOTH map to
      ``force=False``: a graceful stop that NEVER hard-kills and raises
      ``StopTimeout`` ("cannot stop; try force") if the guest is still up. Today's
      default stop killed-after-grace; now you must opt into ``--force``.
      ``--force`` => ``force=True``; ``--timeout N`` => ``timeout=N`` (the grace
      window). ``--force --timeout N`` (grace-then-kill) is now VALID (was a
      ValidationError). ``--graceful-only --force`` stays rejected (contradictory).
      StopTimeout is a KentoError, so ``_handle`` maps it to exit 1 — preserving
      today's non-zero exit for a stop that does not take.
    * **destroy (M7)** — now releases the instance's OWN image hold (prevents
      orphan-hold buildup); ``--force`` => force-stop-then-remove. ``--force``
      absent on a running instance raises ``StateError`` (exit 1), as before.
    """
    from kento import validate_name
    errors = 0
    for container_name in args.name:
        try:
            validate_name(container_name)
            inst = _resolve_instance(container_name, scope)

            if subcmd == "start":
                inst.start()
            elif subcmd in ("shutdown", "stop"):
                force, timeout = _stop_args(args)
                inst.stop(timeout=timeout, force=force)
            elif subcmd in ("destroy", "rm"):
                inst.destroy(force=args.force)
            elif subcmd == "scrub":
                inst.scrub()
        except KentoError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            errors += 1
    if errors:
        sys.exit(1)


def _stop_args(args) -> tuple[bool, int | None]:
    """Map today's stop/shutdown CLI flags onto M6 ``(force, timeout)`` (§11.2).

    * ``--force``          -> ``force=True`` (hard kill; with ``--timeout N`` a
      grace-then-kill window — now VALID, was a ValidationError before M6).
    * ``--graceful-only``  -> ``force=False`` (graceful, never kill — the SAME as
      the new default; the flag is now redundant but still accepted).
    * default / no flags   -> ``force=False`` (graceful, never kill; raises
      ``StopTimeout`` if the guest stays up — the M6 redesign, CHANGELOG'd).
    * ``--timeout N``      -> ``timeout=N`` (the grace window).

    Rejects the one genuinely contradictory combination, ``--graceful-only
    --force`` (force=True vs the explicit never-kill request), with the legacy
    ValidationError so the long-standing guard is preserved.
    """
    from kento.errors import ValidationError

    force = bool(args.force)
    graceful_only = bool(getattr(args, "graceful_only", False))
    timeout = getattr(args, "timeout", None)

    if graceful_only and force:
        raise ValidationError(
            "--graceful-only and --force are mutually exclusive "
            "(--graceful-only never hard-kills; --force always does)."
        )
    # --graceful-only is now exactly the default (M6 force=False never kills),
    # so it folds into force=False; no separate plumbing needed.
    return force, timeout


def _dispatch_info(args, scope: str | None) -> None:
    from kento import require_root, validate_name
    validate_name(args.name)
    require_root()

    # Resolve to a typed Instance via the M1 entry point, narrowed by scope:
    # `kento info`     -> the base Instance (both namespaces, any kind);
    # `kento lxc info` -> SystemContainer (the LXC kind);
    # `kento vm  info` -> VirtualMachine  (the VM kind).
    # A miss / kind mismatch raises InstanceNotFoundError, which the outer
    # _handle wrapper turns into "Error: ..." + exit 1 — preserving today's
    # missing-instance contract. (Disclosed: a SCOPED lookup of a name that is
    # the *other* kind now raises the typed kind-mismatch message rather than the
    # legacy "no <ns> named ..." string; no test pinned that text and the
    # exit code is unchanged.)
    inst = _resolve_instance(args.name, scope)

    # Project the typed snapshot back to TODAY's exact wire via the Block-17
    # projection (the library no longer builds the strings — §11.8 D1).
    from kento_cli import _projection
    if args.as_json:
        print(_projection.instance_to_json(inst, verbose=args.verbose))
    else:
        print(_projection.instance_to_human(inst, verbose=args.verbose))


def _resolve_instance(name: str, scope: str | None):
    """Resolve ``name`` to its typed Instance handle, narrowed by ``scope``.

    ``scope`` maps to the polymorphic ``get`` entry point (§10.1): ``None`` ->
    the base ``Instance`` (both namespaces), ``"lxc"`` -> ``SystemContainer``,
    ``"vm"`` -> ``VirtualMachine``. Raises ``InstanceNotFoundError`` on a miss or
    a kind mismatch.
    """
    if scope == "lxc":
        from kento import SystemContainer
        return SystemContainer.get(name)
    if scope == "vm":
        from kento import VirtualMachine
        return VirtualMachine.get(name)
    from kento import Instance
    return Instance.get(name)


def _dispatch_attach(args, scope: str | None) -> None:
    """Re-pointed ``attach``/``enter`` onto ``Instance.attach`` (M12, §11.3).

    EXIT-CODE DELTA (disclosed, CHANGELOG'd): the typed ``attach() -> None``
    deliberately DROPS the wrapped tool's exit code (§11.3 — an interactive
    console session's last-command exit is not a meaningful result; a clean
    detach and a failing last command are indistinguishable). So ``attach`` now
    exits 0 on a clean detach instead of propagating ``lxc-attach``/``pct
    enter``/``qm terminal``'s code. A genuine failure to attach at all (no serial
    socket, not a tty) is surfaced as a typed ``StateError`` by ``attach.attach``
    -> ``_handle`` -> exit 1, so real failures still report non-zero.
    """
    from kento import validate_name
    validate_name(args.name)
    inst = _resolve_instance(args.name, scope)
    inst.attach()


def _dispatch_set(args, scope: str | None) -> None:
    """Re-pointed ``set`` onto M9 property mutation (§11.2, Phase 6).

    The handle is resolved via the scope-aware ``get`` entry point, then for each
    PROVIDED flag a read-modify-write is done on the matching TYPED property
    (CLASSES-ONLY seam — no legacy ``set_cmd`` dict crosses the boundary):

    * ``--memory``/``--cores`` -> RMW ``inst.resources`` (a ``dict[str, int]`` —
      a spec'd open typed field, §11.0; only the keys passed are replaced).
    * ``--hostname``           -> ``inst.hostname = ...``.
    * ``--port``               -> ``inst.forwards = parse_forwards(specs)``
      (declarative replace — Phase 5; ``--port ''`` clears to ``{}``).
    * ``--lxc-arg``            -> ``inst.lxc_args`` (``SystemContainer`` only).
    * ``--qemu-arg``           -> ``inst.qemu_args`` (``VirtualMachine`` only).
    * ``--pve-arg``            -> ``inst.extra_args`` (PVE-only; the setter's
      ``set_cmd`` enforces PVE validity).
    * ``--network``/``--ip``/``--gateway``/``--dns``/``--mac`` -> RMW
      ``inst.network`` (a whole ``NetworkConnection``; see ``_set_network_rmw``).

    Only the fields the user passed are touched (unprovided ones are left). The
    setters enforce per-field live-ness + catch-reverse INTERNALLY (§11.2 M9) —
    the CLI just assigns; a raised ``KentoError`` (``StateError``/``ModeError``/
    ``ValidationError``/``InstanceNotFoundError``) is mapped to today's exit by
    the outer ``_handle`` wrapper. On success the dispatch returns and the
    process exits 0 — preserving today's set contract (``set_cmd`` returned 0).

    Kind-specific args (``--lxc-arg`` on a VM, ``--qemu-arg`` on an LXC) are
    structurally absent on the wrong typed kind (no setter); we raise the SAME
    ``ModeError`` message ``set_cmd`` used rather than letting a bare
    ``AttributeError`` escape (which ``_handle`` would not catch).
    """
    from kento import (
        SystemContainer,
        VirtualMachine,
        validate_name,
    )
    from kento.errors import ModeError

    validate_name(args.name)
    inst = _resolve_instance(args.name, scope)

    # --memory / --cores -> RMW the resources bag (only the provided keys).
    if args.memory is not None or args.cores is not None:
        resources = dict(inst.resources)
        if args.memory is not None:
            resources["memory"] = args.memory
        if args.cores is not None:
            resources["cores"] = args.cores
        inst.resources = resources

    # --hostname -> the hostname property (stopped-only; set_cmd persists).
    if args.hostname is not None:
        inst.hostname = args.hostname

    # --lxc-arg -> SystemContainer.lxc_args (declarative replace; '' clears).
    if args.lxc_args is not None:
        if not isinstance(inst, SystemContainer):
            raise ModeError(
                "--lxc-arg is not applicable to VM modes (no native LXC config)."
            )
        inst.lxc_args = _set_list_arg(args.lxc_args)

    # --qemu-arg -> VirtualMachine.qemu_args (declarative replace; '' clears).
    if args.qemu_args is not None:
        if not isinstance(inst, VirtualMachine):
            raise ModeError(
                "--qemu-arg is not supported for LXC/PVE-LXC instances; "
                "it applies to VM modes only."
            )
        inst.qemu_args = _set_list_arg(args.qemu_args)

    # --pve-arg -> the extra_args property (PVE-only; setter's set_cmd guards).
    if args.pve_args is not None:
        inst.extra_args = _set_list_arg(args.pve_args)

    # --port -> the forwards map (declarative replace; '' clears to {}).
    if args.port is not None:
        from kento import parse_forwards
        specs = [p for p in args.port if p != ""]
        inst.forwards = parse_forwards(specs)

    # --network / --ip / --gateway / --dns / --mac -> RMW the NetworkConnection.
    if (args.network is not None or args.ip is not None
            or args.gateway is not None or args.dns is not None
            or args.mac is not None):
        _set_network_rmw(inst, args)


def _set_list_arg(values: "list[str]") -> "list[str]":
    """Map the CLI's append-list clear sentinel onto the typed setter's clear.

    The pass-through setters (``lxc_args``/``qemu_args``/``extra_args``) take a
    WHOLE list: a non-empty list REPLACES, an empty list CLEARS. The CLI's
    ``--lxc-arg ''`` clear sentinel arrives as ``['']`` (an all-empty list), so
    strip the empty strings -> ``[]`` clears, ``['x', 'y']`` replaces verbatim.
    """
    return [v for v in values if v != ""]


def _set_network_rmw(inst, args) -> None:
    """RMW the typed ``NetworkConnection`` from the granular set flags (§5.1, M9).

    The CLI's ``--network``/``--ip``/``--gateway``/``--dns``/``--mac`` are
    granular partial edits, but the typed ``network`` property takes a WHOLE
    ``NetworkConnection`` (M9: assign a whole typed value, sub-edits via
    read-modify-write). So we read ``inst.network``, overlay only the provided
    flags using the SAME merge rules ``set_cmd`` applies on-disk (a network-type
    change resets the bridge / clears L3 for non-bridge modes; ``--ip dhcp``
    clears the static address + gateway; etc.), and assign the result. The typed
    setter then re-decomposes the whole value back through ``set_cmd`` (with
    explicit clears) — stopped-only, lock-guarded, catch-reverse internally.

    Mode/identity validity (e.g. usermode is VM-only, ``--ip`` needs bridge) is
    enforced by ``set_cmd`` inside the setter, so an invalid combination raises
    the same typed ``ModeError``/``ValidationError`` as today BEFORE any write.
    """
    from kento import NetworkConnection, NetworkMode
    from kento.errors import ValidationError

    current = inst.network
    link = dict(current.link_config)
    ip_config = dict(current.ip_config)

    # Track the network TYPE-FAMILY separately from the static-address presence,
    # exactly as set_cmd does (set_cmd.py:_resolve_net_identity / merge): the
    # type is "bridge"/"host"/"usermode"/"none", and STATIC-vs-DHCP is decided
    # by whether a static address is present. This separation is what lets us
    # faithfully reproduce set_cmd's identity validation (e.g. `--ip` on a
    # non-bridge type is an ERROR, not silently coerced to STATIC).
    net_type = {
        NetworkMode.STATIC: "bridge",
        NetworkMode.DHCP: "bridge",
        NetworkMode.HOST: "host",
        NetworkMode.USER: "usermode",
        NetworkMode.DISABLED: "none",
    }[current.mode]

    # --network: change the type (and reset the bridge unless one is named),
    # mirroring set_cmd's identity merge (set_cmd.py:529-539).
    if args.network is not None:
        req_type, req_bridge = _parse_network_for_set(args.network)
        net_type = req_type
        if req_type == "bridge":
            if req_bridge is not None:
                link["bridge"] = req_bridge
            # else keep the current bridge.
        else:
            # A non-bridge type drops the bridge + any static L3 (set_cmd resets
            # bridge to None; the non-bridge modes carry no ip_config, §5.2).
            link.pop("bridge", None)
            ip_config.pop("address", None)
            ip_config.pop("subnet", None)
            ip_config.pop("gateway", None)
            ip_config.pop("dns1", None)

    # --ip: 'dhcp' clears the static address (+ gateway); else set a static
    # address. --ip does NOT change the type-family (set_cmd.py:541-546); an
    # --ip on a non-bridge type is caught by the identity guard below.
    if args.ip is not None:
        if args.ip == "dhcp":
            ip_config.pop("address", None)
            ip_config.pop("subnet", None)
            ip_config.pop("gateway", None)  # gateway is meaningless w/o static
        else:
            from kento import parse_cidr
            address, subnet = parse_cidr(args.ip)
            ip_config["address"] = address
            if subnet is not None:
                ip_config["subnet"] = subnet
            else:
                ip_config.pop("subnet", None)

    # --gateway / --dns: L3 fields ('' clears; set_cmd.py:547-550).
    if args.gateway is not None:
        if args.gateway:
            ip_config["gateway"] = args.gateway
        else:
            ip_config.pop("gateway", None)
    if args.dns is not None:
        if args.dns:
            ip_config["dns1"] = args.dns
        else:
            ip_config.pop("dns1", None)

    # --mac: an L2 NIC attribute (link_config); VM-only validity is enforced by
    # set_cmd inside the setter (raises ModeError on an LXC instance).
    if args.mac is not None:
        link["mac"] = args.mac

    # Identity guards mirroring set_cmd._validate_net_identity (set_cmd.py:361-
    # 369) for the rules the typed decomposition cannot reproduce on its own
    # (gate C — preserve today's errors; no silent data loss). Mode-family ×
    # backend validity (usermode VM-only, host LXC-only, etc.) IS reproduced by
    # the typed setter's set_cmd, so it is not re-checked here.
    has_static = bool(ip_config.get("address"))
    if args.ip is not None and args.ip != "dhcp" and net_type != "bridge":
        raise ValidationError(
            "--ip requires bridge networking (--network bridge=<name>); "
            f"the resulting network type is {net_type!r}."
        )
    if args.gateway is not None and args.gateway and not has_static:
        raise ValidationError(
            "--gateway requires a static --ip (a gateway has no meaning "
            "without a static address)."
        )

    # Map the resolved (type-family, static-presence) back to the typed mode.
    if net_type == "bridge":
        mode = NetworkMode.STATIC if has_static else NetworkMode.DHCP
    else:
        mode = {
            "host": NetworkMode.HOST,
            "usermode": NetworkMode.USER,
            "none": NetworkMode.DISABLED,
        }[net_type]

    inst.network = NetworkConnection(
        mode=mode, link_config=link, ip_config=ip_config,
    )


def _parse_network_for_set(network: str) -> "tuple[str, str | None]":
    """Parse a ``set --network`` value into ``(net_type, bridge_name)``.

    Accepts the same surface as ``create``'s ``--network``: ``bridge``,
    ``bridge=<name>``, ``host``, ``usermode``, ``none``. Mode-vs-type validity is
    enforced later by the typed setter's ``set_cmd`` against the resolved
    instance (so the message reflects the actual instance). Mirrors
    ``set_cmd._parse_network_arg``.
    """
    from kento.errors import ValidationError

    if network in ("host", "usermode", "none", "bridge"):
        return network, None
    if network.startswith("bridge="):
        name = network.split("=", 1)[1]
        if not name:
            raise ValidationError(
                "--network bridge=<name> requires a bridge name."
            )
        return "bridge", name
    raise ValidationError(
        f"unknown --network value {network!r}; expected one of "
        "bridge, bridge=<name>, host, usermode, none."
    )


def _resolve_vm(name: str, scope: str | None):
    """Resolve ``name`` to a ``VirtualMachine`` handle for suspend/resume (§11.4).

    ``suspend``/``resume`` are VM-only (M17/M18 live on ``VirtualMachine``).
    Resolve via the scope-aware ``get`` (so ``kento vm suspend`` narrows, bare
    ``kento suspend`` resolves the concrete kind), then reject a non-VM with the
    legacy LXC-unsupported ``ModeError`` message so today's rejection text + exit
    1 are preserved (a bare LXC name would otherwise surface ``get``'s
    kind-mismatch error instead of the suspend/resume guidance).
    """
    inst = _resolve_instance(name, scope)
    from kento import VirtualMachine
    if not isinstance(inst, VirtualMachine):
        from kento.errors import ModeError
        raise ModeError(
            "suspend/resume is not supported for LXC instances; "
            "use 'kento stop' / 'kento start'."
        )
    return inst


def _dispatch_suspend(args, scope: str | None) -> None:
    """Re-pointed ``suspend`` onto ``VirtualMachine.suspend`` (M17, §11.4)."""
    from kento import validate_name
    validate_name(args.name)
    _resolve_vm(args.name, scope).suspend()


def _dispatch_resume(args, scope: str | None) -> None:
    """Re-pointed ``resume`` onto ``VirtualMachine.resume`` (M18, §11.4)."""
    from kento import validate_name
    validate_name(args.name)
    _resolve_vm(args.name, scope).resume()


def _dispatch_exec(args, scope: str | None) -> None:
    """Re-pointed ``exec`` onto ``SystemContainer.exec`` (M13, §11.3).

    ``exec`` is LXC-only (the method lives on ``SystemContainer``; a VM has no
    in-guest agent). Resolve via the scope-aware ``get``, reject a non-LXC kind
    with the legacy ``ModeError`` text (so ``kento vm exec`` / a bare VM name
    still report "use attach/SSH" + exit 1), then run the command and propagate
    its exit code (M13 ``exec -> int`` — non-zero is a result, not an error, and
    is passed straight through to ``sys.exit``, preserving today's contract).
    """
    from kento import validate_name
    validate_name(args.name)
    # argparse.REMAINDER captures a leading '--' verbatim; strip it so both
    # 'kento exec foo -- ls -la' and 'kento exec foo ls -la' pass the same
    # command list to exec.
    command = list(args.exec_command)
    if command and command[0] == "--":
        command = command[1:]
    inst = _resolve_lxc(args.name, scope, what="exec")
    sys.exit(inst.exec(command))


def _resolve_lxc(name: str, scope: str | None, *, what: str):
    """Resolve ``name`` to a ``SystemContainer`` handle for exec/logs (§11.3).

    ``exec``/``logs`` are LXC-only (the methods live on ``SystemContainer``).
    Resolve via the scope-aware ``get``, then reject a non-LXC kind with the
    runtime's own ``ModeError`` text so ``kento vm exec``/``kento vm logs`` (and
    a bare VM name) keep today's "use attach/SSH" rejection + exit 1 rather than
    surfacing ``get``'s kind-mismatch error or an ``AttributeError``.
    """
    inst = _resolve_instance(name, scope)
    from kento import SystemContainer
    if not isinstance(inst, SystemContainer):
        from kento.errors import ModeError
        raise ModeError(
            f"{what} is only supported for LXC/PVE-LXC instances "
            "(use attach or SSH for VMs)."
        )
    return inst


def _dispatch_logs(args, scope: str | None) -> None:
    """Re-pointed ``logs`` onto ``SystemContainer.logs`` (M14, §11.3).

    Jei-ruled M14 refinement: the legacy CLI's arbitrary ``journalctl``
    pass-through is PRESERVED. The whole REMAINDER (``-f``, ``-n 50``,
    ``--since ...``, ``-u sshd``, ...) is forwarded verbatim as the typed method's
    ``args`` pass-through; ``journalctl`` itself interprets them — byte-identical
    to the pre-Phase-6 ``logs.logs(name, args)`` invocation. (``follow``/``lines``
    stay typed conveniences on the library method for programmatic callers; the
    CLI uses the raw pass-through to keep the full journalctl surface.) The typed
    method returns an ``Iterator[str]`` of decoded lines; we print each + flush so
    a ``-f`` tail streams live, exit 0 at EOF (or 1 on a typed raise via
    ``_handle``). LXC-only — a VM is rejected with ``ModeError``, preserving
    today's rejection.
    """
    from kento import validate_name
    validate_name(args.name)
    # Strip a leading '--' that argparse.REMAINDER may have captured, then pass
    # the rest straight through to journalctl (restores today's pass-through).
    extra = list(args.args)
    if extra and extra[0] == "--":
        extra = extra[1:]
    inst = _resolve_lxc(args.name, scope, what="logs")
    for line in inst.logs(args=extra):
        # Each yielded line is already newline-free (the streamer splits on
        # newlines); print restores the newline. Flush per line so a live
        # `-f` tail appears immediately rather than buffered.
        print(line, flush=True)


def _dispatch_list(args, scope: str | None) -> None:
    # Enumerate via the M2 entry point, narrowed by scope (same scope->class
    # mapping as info): base Instance for `kento list`, SystemContainer for
    # `kento lxc list`, VirtualMachine for `kento vm list`.
    if scope == "lxc":
        from kento import SystemContainer as _Cls
    elif scope == "vm":
        from kento import VirtualMachine as _Cls
    else:
        from kento import Instance as _Cls
    insts = _Cls.list()

    # JC6 — preserve today's `list` wire byte-for-byte. The legacy list.py SKIPS
    # an entry whose status probe is INDETERMINATE (an unreadable PVE config or a
    # raising is_running -> its `except OSError: continue`). The typed status
    # resolver instead yields Status.UNKNOWN for exactly that case (a real domain
    # state, total over the store). To match the legacy wire (seadog reads it) we
    # drop the UNKNOWN rows here, in the handler, so the projected array/table is
    # byte-identical to today's. This is cleanly distinguishable (status is
    # exactly UNKNOWN), so it is a filter, not an intentional improvement.
    # (Genuinely corrupt/raced entries are already skipped INSIDE Instance.list,
    # mirroring list.py; this filter only handles the indeterminate-probe case.)
    from kento import Status
    insts = [i for i in insts if i.status is not Status.UNKNOWN]

    from kento_cli import _projection
    show_size = getattr(args, "show_size", False)
    if getattr(args, "as_json", False):
        print(_projection.instances_to_json(insts, show_size=show_size))
    else:
        print(_projection.instances_to_human(insts, show_size=show_size))


def _dispatch_diagnose(args) -> None:
    """Re-pointed `kento diagnose [NAME] [--json]` (Phase 6, Block 18).

    diagnose degrades without root (the scan handles it); do NOT require_root().
    getattr guards against the top-level positional `name` being absent /
    collapsed to "" by the argparse layer.

    Both scopes map onto the SAME typed entry point — the module-level
    ``kento.diagnose(name)`` FUNCTION (the shadow foot-gun: ``from kento import
    diagnose`` is the function, NOT the ``kento.diagnose`` submodule). It returns
    a typed ``Diagnosis`` (classes-only across the seam — no dict crosses, and
    the CLI no longer imports any library internals):

    * NO name (host-wide): ``kento.diagnose(None)`` -> ALL findings (all three
      domains) for the whole-host scan.
    * a NAME: ``kento.diagnose(name)`` -> the HOST checks + that one resolved
      instance's checks, UNFILTERED (preserving today's named wire). The library
      narrows via ``run_diagnostics(name)`` and projects without a domain/subject
      filter — deliberately NOT ``instance.diagnose()``'s INSTANCE+self filter,
      which would drop the host findings and break the wire. An unknown name
      raises ``InstanceNotFoundError`` (propagated from the library) -> the
      shared ``_handle`` maps it to "Error: ..." + exit 1.

    ``instances_scanned`` is caller-supplied to the projection (the typed
    ``Diagnosis`` carries no count — §11.8 D3): the host-wide count is
    ``len(Instance.list())`` (the same ``*/kento-image`` enumeration over both
    bases ``run_diagnostics(None)`` uses); the named count is ``1`` (a named scan
    visits exactly one resolved instance). This is display metadata derived from
    TYPED objects, not a dict crossing. Exit ``1`` iff there are problems
    (WARNING/ERROR), else ``0`` — the same ``problem_count``-driven contract.
    """
    from kento_cli import _projection

    name = getattr(args, "name", None) or None

    import kento
    diag = kento.diagnose(name=name)  # raises InstanceNotFoundError on a miss

    if name is None:
        # The host-wide enumeration count (matches run_diagnostics(None)'s
        # len(enumerated dirs); see _projection.diagnosis_to_wire_dict on why the
        # count must be caller-supplied rather than finding-derived). Disclosed
        # edge: Instance.list drops an entry its snapshot loader cannot read,
        # while run_diagnostics' enumerate drops only on OSError reading the
        # mode; in the normal store the two counts agree.
        from kento import Instance
        instances_scanned = len(Instance.list())
    else:
        # A named scan visits exactly one resolved instance.
        instances_scanned = 1

    if args.as_json:
        print(_projection.diagnosis_to_json(
            diag, instances_scanned=instances_scanned))
    else:
        print(_projection.diagnosis_to_human(
            diag, instances_scanned=instances_scanned))

    sys.exit(1 if diag.problems else 0)


def _format_image_prune(report) -> str:
    """Render an Image.prune ReclaimReport (M22/M25) as human text.

    ``Image.prune`` always EXECUTES (the M22 signature has no ``dry_run`` — the
    returned report is always ``dry_run=False``), so this renders an outcome
    summary, never a dry-run plan: how many dangling images were reclaimed, with
    any podman refusals surfaced (the 1.6.2 failure-surfacing contract) as
    ``(image, reason)`` lines. ``report`` is a typed ``ReclaimReport`` (a frozen
    dataclass) — classes-only across the seam, never a dict.
    """
    n = len(report.reclaimed)
    lines = [f"Removed {n} dangling image(s)."]
    if report.failed:
        lines.append(
            f"Failed to remove {len(report.failed)} image(s) "
            "(held, still referenced, or accounting mismatch):"
        )
        for image, reason in report.failed:
            lines.append(f"  {image}: {reason}")
    return "\n".join(lines)


def _format_orphan_prune(report) -> str:
    """Render an Instance.prune_orphans ReclaimReport (M4/M25) as human text.

    Unlike image prune, ``prune_orphans`` is dry-run-able: ``report.dry_run`` is
    ``True`` when invoked without ``--yes`` (nothing destroyed — the report lists
    what WOULD be reaped, with a ``--yes`` hint) and ``False`` after a real reap
    (each orphan reported reaped, failures surfaced). ``report`` is a typed
    ``ReclaimReport`` — classes-only, never a dict.
    """
    if report.dry_run:
        if not report.reclaimed:
            return "Orphans: none found."
        lines = [
            "Orphans:",
            f"  Dry run — nothing destroyed. {len(report.reclaimed)} orphaned "
            "instance(s) WOULD be destroyed (state discarded):",
        ]
        for name in report.reclaimed:
            lines.append(f"    {name}")
        lines.append("  Run 'kento prune --orphans --yes' to destroy them.")
        return "\n".join(lines)

    if not report.reclaimed and not report.failed:
        return "Orphans: none found."
    lines = ["Orphans:"]
    for name in report.reclaimed:
        lines.append(f"  reaped {name}")
    for name, reason in report.failed:
        lines.append(f"  FAILED {name}: {reason}")
    n_failed = len(report.failed)
    summary = f"Destroyed {len(report.reclaimed)} orphan(s)"
    summary += f", {n_failed} failed." if n_failed else "."
    lines.append(summary)
    return "\n".join(lines)


def _dispatch_pull(args) -> None:
    """Pull an OCI image into the local store via the typed library (M19).

    Re-pointed (Phase 6) from a raw ``podman pull`` subprocess onto
    ``kento.OciImage.pull(ref)``, which acquires the image and returns a resolved
    typed handle. CLASSES-ONLY across the seam: the library hands back an
    ``Image`` (an ``OciImage``); the CLI keeps only its rendered ``source``
    for the success line and discards the rest.

    Behavior deltas vs the old raw subprocess (CHANGELOG'd):

    * **Progress display.** ``Image.pull`` runs podman with captured output
      (M19 has no progress callback — deferred post-1.0, spec §11.7), so the
      live layer-pull progress the raw subprocess streamed is no longer shown;
      a one-line confirmation prints on success instead. Failure output is
      surfaced in the raised ``SubprocessError`` message.
    * **Ref validation.** A malformed reference now raises ``MalformedReference``
      (mapped by ``_handle`` to "Error: ..." + exit 1) BEFORE any podman call,
      instead of being handed to the shell.

    Exit codes are preserved by the outer ``_handle`` wrapper: podman absent
    (``SubprocessError`` with ``returncode=None``) -> exit 2; any other pull
    failure -> exit 1. (The old handler special-cased podman-absent to exit 2
    with its own message; ``_exit_code`` reproduces the 2, the library supplies
    the message.)
    """
    import kento

    kento.require_root()
    # Spec §11.5 phrases this `Image.pull`; the as-built classmethod lives on the
    # concrete `OciImage` (Image and LayeredImage are genuine ABCs).
    image = kento.OciImage.pull(args.image)
    print(f"Pulled {image.source.render()}")


if __name__ == "__main__":
    main()
