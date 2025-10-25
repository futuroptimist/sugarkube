"""Utilities for Avahi command construction and hostname normalisation."""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence


def build_publish_cmd(
    *,
    instance: str,
    service_type: str,
    port: int,
    host: str | None,
    txt: Mapping[str, str] | None,
) -> list[str]:
    """Return an ``avahi-publish`` command with TXT pairs as discrete args."""

    command = ["avahi-publish", "-s"]
    if host:
        command.extend(["-H", host])
    command.extend([instance, service_type, str(port)])
    if txt:
        command.extend(f"{key}={value}" for key, value in txt.items())
    return command


def serialize_publish_cmd(command: Sequence[str]) -> str:
    """Render a command list for logging without flattening TXT pairs."""

    joined = ", ".join(repr(part) for part in command)
    return f"[{joined}]"


def norm_host(host: str | None) -> str:
    """Lower-case hostnames and strip the trailing dot for equality checks."""

    return (host or "").rstrip(".").lower()


def normalize_hostname(host: str | None) -> str:
    """Backwards-compatible alias for :func:`norm_host`."""

    return norm_host(host)


def build_publish_command(
    *,
    instance: str,
    service_type: str,
    port: int,
    host: str | None,
    txt: Mapping[str, str] | None,
) -> list[str]:
    """Compatibility wrapper for the historic helper name."""

    return build_publish_cmd(
        instance=instance,
        service_type=service_type,
        port=port,
        host=host,
        txt=txt,
    )


def iter_norm_hosts(hosts: Iterable[str | None]) -> list[str]:
    """Return normalised hostnames for logging convenience."""

    return [norm_host(host) for host in hosts]


_norm_host = norm_host

__all__ = [
    "build_publish_cmd",
    "build_publish_command",
    "iter_norm_hosts",
    "norm_host",
    "normalize_hostname",
    "serialize_publish_cmd",
    "_norm_host",
]
