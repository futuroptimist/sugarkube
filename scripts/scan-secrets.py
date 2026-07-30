#!/usr/bin/env python3
"""Scan input diff for potential secrets.

The script reads a unified diff from stdin and searches for high-risk patterns
such as API keys or tokens. If `ripsecrets` is available it will be used for a
more thorough scan; otherwise a lightweight regex-based fallback is used. Any
findings are printed to stderr so they don't pollute stdout.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable

SCAN_SCRIPT_PATH = "scripts/scan-secrets.py"

PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"https://hc-ping\.com/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        re.IGNORECASE,
    ),
    re.compile(r"aws(.{0,20})?(?:secret|access)_key", re.IGNORECASE),
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"token\s*[:=]", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
)

HEALTHCHECKS_URL = re.compile(
    r"https://hc-ping\.com/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)
HEALTHCHECKS_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-" r"[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)

# Exact metadata placeholders are identifiers, not credential values. Keep this
# deliberately narrow: trailing content must still be scanned.
SAFE_PLACEHOLDERS = (
    re.compile(r"^\+\s*passwordKey:\s*admin-password\s*$"),
    re.compile(r"^\+\s*-\s*Password key:\s*`admin-password`\.\s*$"),
    # This is a file descriptor, not a value. It is the required safe shape for
    # piping a cert-manager token without exposing it in argv.
    re.compile(
        r"^\+(?!.*(?:password|api[_-]?key))"
        r"(?!.*token\s*[:=](?!/dev/stdin)).*--from-file=api-token=/dev/stdin.*$",
        re.IGNORECASE,
    ),
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
    except OSError as exc:  # pragma: no cover - subprocess execution failure
        print(f"Failed to run ripsecrets: {exc}", file=sys.stderr)
        os.unlink(tmp_path)
        return None
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    if result.returncode != 0:
        # ripsecrets prints findings to stdout; non-zero means potential secret
        diagnostic = result.stdout or result.stderr
        diagnostic = HEALTHCHECKS_URL.sub("[REDACTED HEALTHCHECKS URL]", diagnostic)
        diagnostic = HEALTHCHECKS_UUID.sub("[REDACTED HEALTHCHECKS UUID]", diagnostic)
        print(diagnostic, file=sys.stderr)
        return True
    return False


def regex_scan(lines: Iterable[str]) -> bool:
    """Return True if any added line matches a high-risk pattern."""
    file_path = None
    for line in lines:
        if line.startswith("+++"):
            file_path = line[4:].strip()
            continue
        if not line.startswith("+"):
            continue
        if file_path and file_path.endswith(SCAN_SCRIPT_PATH):
            continue
        if not any(pattern.fullmatch(line) for pattern in SAFE_PLACEHOLDERS):
            for pattern in PATTERNS:
                if pattern.search(line):
                    print(
                        f"Possible secret detected in {file_path or 'unknown path'} "
                        "(value redacted).",
                        file=sys.stderr,
                    )
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
    if regex_scan(diff.splitlines()):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
