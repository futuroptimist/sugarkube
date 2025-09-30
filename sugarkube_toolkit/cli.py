"""Entry points for the sugarkube CLI."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from . import runner

DOC_VERIFY_COMMANDS: list[list[str]] = [
    ["pyspelling", "-c", ".spellcheck.yaml"],
    ["linkchecker", "--no-warnings", "README.md", "docs/"],
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sugarkube",
        description="Unified helpers for Sugarkube automation workflows.",
    )
    parser.set_defaults(handler=None)

    subparsers = parser.add_subparsers(dest="section")

    docs_parser = subparsers.add_parser(
        "docs",
        help="Documentation workflows (spellcheck, link validation, and more).",
    )
    docs_subparsers = docs_parser.add_subparsers(dest="command")

    verify_parser = docs_subparsers.add_parser(
        "verify", help="Run pyspelling and linkchecker like the docs describe."
    )
    verify_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the commands without executing them.",
    )
    verify_parser.set_defaults(handler=_handle_docs_verify)

    return parser


def _handle_docs_verify(args: argparse.Namespace) -> int:
    try:
        runner.run_commands(DOC_VERIFY_COMMANDS, dry_run=args.dry_run)
    except runner.CommandError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)
