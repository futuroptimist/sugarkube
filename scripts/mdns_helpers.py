"""Utilities for mDNS publishing and hostname normalization."""
from __future__ import annotations

from typing import Final, Mapping

_LOCAL_SUFFIXES: Final = (".local",)
_CONTROL_CHAR_MAP: Final = {i: None for i in range(32)}
_CONTROL_CHAR_MAP.update({0x7F: None})


def norm_host(host: str | None) -> str:
    """Return a lowercase hostname without a trailing period."""

    if not host:
        return ""

    candidate = host.translate(_CONTROL_CHAR_MAP).strip()
    if not candidate:
        return ""

    return candidate.rstrip(".").lower()


def normalize_hostname(host: str) -> str:
    """Backwards compatible wrapper around :func:`norm_host`."""

    return norm_host(host)


# Backwards compatible alias for k3s_mdns_parser imports
_norm_host = norm_host


def _strip_local_suffix(host: str) -> str:
    """Remove any trailing ``.local`` suffixes."""

    for suffix in _LOCAL_SUFFIXES:
        while host.endswith(suffix):
            host = host[: -len(suffix)]
    return host


def _same_host(left: str, right: str) -> bool:
    """Return ``True`` if two host strings refer to the same machine."""

    left_norm = norm_host(left)
    right_norm = norm_host(right)
    if not left_norm or not right_norm:
        return False

    if left_norm == right_norm:
        return True

    return _strip_local_suffix(left_norm) == _strip_local_suffix(right_norm)


def build_publish_cmd(
    *,
    instance: str,
    service_type: str,
    port: int,
    host: str | None,
    txt: Mapping[str, str],
) -> list[str]:
    """Construct an ``avahi-publish`` command in the documented order."""

    command = ["avahi-publish", "-s"]
    if host:
        command.extend(["-H", host])
    command.extend([instance, service_type, str(port)])
    if txt:
        for key, value in txt.items():
            command.append(f"{key}={value}")
    return command


# Preserve the previous public name for compatibility with older callers.
build_publish_command = build_publish_cmd


__all__ = [
    "build_publish_cmd",
    "build_publish_command",
    "norm_host",
    "normalize_hostname",
    "_norm_host",
    "_same_host",
]
