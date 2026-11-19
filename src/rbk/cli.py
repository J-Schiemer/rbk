"""rbk command-line interface.

This module owns argument parsing and dispatch only. The execution engine
(run), workspace discovery, and the interactive recorder are not implemented
yet; each subcommand currently exits with a clear message.

Planned layout as the engine lands:

* ``rbk list``   — top-level runbooks, hiding ``_``-prefixed fragments
* ``rbk run``    — resolve includes/vars, then stream commands locally or over SSH
* ``rbk record`` — capture an interactive shell session into a YAML runbook

Workspace discovery order: ``--dir`` > ``$RBK_DIR`` > nearest parent directory
containing ``runbooks/`` or ``inventory.yaml``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from rbk import __version__


def _not_implemented(command: str) -> int:
    print(f"rbk {command}: not implemented yet", file=sys.stderr)
    return 2


def _parse_var(raw: str) -> tuple[str, str]:
    key, sep, value = raw.partition("=")
    if not sep or not key:
        raise argparse.ArgumentTypeError(f"expected KEY=VALUE, got {raw!r}")
    return key, value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rbk",
        description="Lightweight, Git-native CLI runbook runner over plain OpenSSH.",
    )
    parser.add_argument("--version", action="version", version=f"rbk {__version__}")
    parser.add_argument(
        "--dir",
        metavar="PATH",
        help="runbook workspace directory (overrides $RBK_DIR and discovery)",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    subparsers.add_parser("list", help="list top-level runbooks")

    run = subparsers.add_parser("run", help="execute a runbook")
    run.add_argument("name", help="runbook name, with or without the .yaml suffix")
    run.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    run.add_argument(
        "--var",
        dest="vars",
        action="append",
        type=_parse_var,
        default=[],
        metavar="KEY=VALUE",
        help="override a variable (repeatable)",
    )

    record = subparsers.add_parser("record", help="record a session into a new runbook")
    record.add_argument("title", help="title for the new runbook")
    record.add_argument("--host", metavar="ALIAS", help="record over ssh instead of locally")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return _not_implemented(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
