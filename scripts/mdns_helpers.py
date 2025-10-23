"""Common helpers for mDNS host normalization."""
from __future__ import annotations

from typing import Optional


def _norm_host(host: str) -> str:
    """Return a lowercase, trailing-dot-free representation of ``host``."""

    host = host.strip().lower()
    while host.endswith("."):
        host = host[:-1]
    return host


def _strip_suffix(host: str, suffix: str) -> str:
    suffix = suffix.strip().lower()
    if not suffix:
        return host
    dot_suffix = f".{suffix.lstrip('.')}"
    if host.endswith(dot_suffix):
        return host[: -len(dot_suffix)]
    return host


def _same_host(lhs: str, rhs: str, *, domain: Optional[str] = None) -> bool:
    """Compare host labels, tolerating case, trailing dots, and .local suffixes."""

    lhs_norm = _norm_host(lhs)
    rhs_norm = _norm_host(rhs)
    if lhs_norm == rhs_norm:
        return True

    suffixes = []
    if domain:
        domain_norm = domain.strip().rstrip(".").lower()
        if domain_norm:
            suffixes.append(domain_norm)
    suffixes.append("local")

    for suffix in suffixes:
        lhs_trimmed = _strip_suffix(lhs_norm, suffix)
        rhs_trimmed = _strip_suffix(rhs_norm, suffix)
        if lhs_trimmed == rhs_trimmed:
            return True

    return False


__all__ = ["_norm_host", "_same_host"]
