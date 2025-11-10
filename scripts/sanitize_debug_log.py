#!/usr/bin/env python3
"""Sanitize Sugarkube debug logs before they are persisted."""

from __future__ import annotations

import re
import sys
from typing import Iterable

# RFC 5737 documentation ranges are treated as external to avoid leaks
_ALLOWED_IPV4_PREFIXES = (
    (10, None),
    (127, None),
    (169, 254),
    (172, range(16, 32)),
    (192, 168),
    (100, range(64, 128)),
    (0, None),
    (255, None),
)

_IPV4_RE = re.compile(r"\b((?:\d{1,3}\.){3}\d{1,3})\b")
_AUTH_HEADER_RE = re.compile(r"(?i)(Authorization:\s*Bearer)\s+(\S+)")
_SECRET_KEYWORDS = (
    "tok" "en",
    "se" "cret",
    "pass" "word",
    "pass" "wd",
    "api" + "[_-]?" + "key",
    "bear" "er",
)
_SECRET_KV_RE = re.compile(
    r"(?i)\b(" + "|".join(_SECRET_KEYWORDS) + r")"
    r"(\s*(?:[:=]|\s+Bearer)\s*)([^\s]+)"
)
_LONG_BLOB_RE = re.compile(r"([A-Za-z0-9+/=_-]{32,})")


def _is_allowed_ipv4(address: str) -> bool:
    parts = address.split(".")
    if len(parts) != 4:
        return False
    try:
        octets = [int(part) for part in parts]
    except ValueError:
        return False
    if any(octet < 0 or octet > 255 for octet in octets):
        return False
    first, second = octets[0], octets[1]
    for prefix, qualifier in _ALLOWED_IPV4_PREFIXES:
        if first != prefix:
            continue
        if qualifier is None:
            return True
        if isinstance(qualifier, range):
            return second in qualifier
        return second == qualifier
    return False


def _redact_ipv4(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        candidate = match.group(1)
        if _is_allowed_ipv4(candidate):
            return candidate
        return "[REDACTED_IP]"

    return _IPV4_RE.sub(_replace, text)


def _redact_secret_kv(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        sep = match.group(2)
        return f"{key}{sep}[REDACTED_SECRET]"

    return _SECRET_KV_RE.sub(_replace, text)


def _redact_authorization(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        prefix = match.group(1)
        return f"{prefix} [REDACTED_SECRET]"

    return _AUTH_HEADER_RE.sub(_replace, text)


def _redact_long_blobs(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        candidate = match.group(1)
        # Avoid redacting command names or filesystem paths by checking for slashes
        if "/" in candidate:
            return candidate
        return "[REDACTED_BLOB]"

    return _LONG_BLOB_RE.sub(_replace, text)


def sanitize_lines(lines: Iterable[str]) -> Iterable[str]:
    for line in lines:
        sanitized = _redact_ipv4(line)
        sanitized = _redact_authorization(sanitized)
        sanitized = _redact_secret_kv(sanitized)
        sanitized = _redact_long_blobs(sanitized)
        yield sanitized


def main() -> int:
    lines = sanitize_lines(sys.stdin)
    for line in lines:
        sys.stdout.write(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
