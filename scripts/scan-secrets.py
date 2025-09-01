#!/usr/bin/env python3
"""Scan input diff for potential secrets.

The script reads a unified diff from stdin and searches for high-risk patterns
such as API keys or tokens. If `ripsecrets` is available it will be used for a
more thorough scan; otherwise a lightweight regex-based fallback is used.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable

SCAN_SCRIPT_PATH = "b/scripts/scan-secrets.py"

PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"aws(.{0,20})?(?:secret|access)_key", re.IGNORECASE),
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"token\s*[:=]", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
)


def run_ripsecrets(diff_text: str) -> bool | None:
    """Return True if secrets found via ripsecrets, False if clean.

    Returns None if ripsecrets is unavailable.
    """
    if not shutil.which("ripsecrets"):
        return None
    with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
        tmp.write(diff_text)
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            ["ripsecrets", tmp_path],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        os.unlink(tmp_path)
    if result.returncode != 0:
        # ripsecrets prints findings to stdout; non-zero means potential secret
        print(result.stdout or result.stderr, file=sys.stderr)
        return True
    return False


def regex_scan(lines: Iterable[str]) -> bool:
    """Return True if any added line matches a high-risk pattern."""
    file_path = None
    for line in lines:
        if line.startswith("+++"):
            file_path = line[4:].strip()
            continue
        if not line.startswith("+") or file_path == SCAN_SCRIPT_PATH:
            continue
        for pattern in PATTERNS:
            if pattern.search(line):
                print(f"Possible secret: {line.rstrip()}")
                return True
    return False


def main() -> int:
    diff = sys.stdin.read()
    if not diff.strip():
        print("No diff provided; skipping secret scan.", file=sys.stderr)
        return 0
    rip = run_ripsecrets(diff)
    if rip is True:
        return 1
    if rip is False:
        return 0
    if regex_scan(diff.splitlines()):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
