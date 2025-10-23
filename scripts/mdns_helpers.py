"""Utilities for normalising and comparing mDNS hostnames."""
from __future__ import annotations

from typing import Final

_LOCAL_SUFFIXES: Final = (".local",)


def _norm_host(host: str) -> str:
    """Normalise a hostname for comparison.

    Avahi is relaxed about emitting trailing dots and mixed case. The
    sugarkube mDNS checks treat hostnames as case-insensitive, so this helper
    ensures callers can compare values without mutating the original string
    used for publication.
    """

    host = host.strip()
    if not host:
        return ""

    while host.endswith("."):
        host = host[:-1]

    return host.lower()


def _strip_local_suffix(host: str) -> str:
    for suffix in _LOCAL_SUFFIXES:
        if host.endswith(suffix):
            return host[: -len(suffix)]
    return host


def _same_host(left: str, right: str) -> bool:
    """Return True when two hosts refer to the same machine."""

    left_norm = _norm_host(left)
    right_norm = _norm_host(right)
    if not left_norm or not right_norm:
        return False

    if left_norm == right_norm:
        return True

    return _strip_local_suffix(left_norm) == _strip_local_suffix(right_norm)


__all__ = ["_norm_host", "_same_host"]
