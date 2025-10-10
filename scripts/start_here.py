#!/usr/bin/env python3
"""Display the Start Here guide path or contents for quick reference."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "start-here.md"


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser."""

    parser = argparse.ArgumentParser(
        description="Surface the Sugarkube Start Here handbook from the command line.",
    )
    parser.add_argument(
        "--path-only",
        action="store_true",
        help="Print just the absolute path to docs/start-here.md.",
    )
    parser.add_argument(
        "--no-content",
        action="store_true",
        help=(
            "Deprecated alias for --path-only; kept for forwards compatibility with early drafts."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the start-here helper."""

    parser = build_parser()
    args = parser.parse_args(argv)

    if not DOC_PATH.exists():
        parser.error("docs/start-here.md is missing; re-run after restoring the handbook.")

    if args.no_content:
        print(
            "WARNING: --no-content is deprecated; use --path-only instead.",
            file=sys.stderr,
        )

    if args.path_only or args.no_content:
        print(DOC_PATH)
        return 0

    print(f"Sugarkube Start Here guide: {DOC_PATH}")
    print()
    print(_strip_front_matter(DOC_PATH.read_text(encoding="utf-8")))
    return 0


def _strip_front_matter(text: str) -> str:
    if text.startswith("\ufeff"):
        text = text[1:]

    if not text.lstrip().startswith("---"):
        return text

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text

    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            remainder_start = idx + 1
            return "".join(lines[remainder_start:])

    return text


if __name__ == "__main__":  # pragma: no cover - exercised via CLI
    raise SystemExit(main(sys.argv[1:]))
