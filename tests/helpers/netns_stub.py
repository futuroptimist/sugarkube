"""Stubs for environments without network namespace privileges."""

from __future__ import annotations

import os
from typing import Mapping, TypedDict


class NetnsStub(TypedDict, total=False):
    ns1: str
    ns2: str
    veth1: str
    veth2: str
    ip1: str
    ip2: str
    stubbed: bool


def netns_stub_mode(env: Mapping[str, str] | None = None) -> str:
    """Return the configured stub mode for network namespaces.

    Supported values:
    - "force": always use stubbed namespaces
    - "auto": attempt real namespaces, fall back to stubs on permission errors
    - "off": require real namespaces
    """

    env = os.environ if env is None else env
    value = env.get("SUGARKUBE_ALLOW_NETNS_STUBS", "").strip().lower()
    if value in {"1", "true", "yes", "force"}:
        return "force"
    if value == "auto":
        return "auto"
    return "off"


def should_stub_netns_setup(env: Mapping[str, str] | None = None) -> bool:
    """Return True when callers request stubbed network namespaces.

    Setting ``SUGARKUBE_ALLOW_NETNS_STUBS=1`` opts into a simulated namespace layout
    so tests can exercise higher-level logic even when CAP_NET_ADMIN is unavailable.
    """

    return netns_stub_mode(env) == "force"


def stub_netns_environment() -> NetnsStub:
    """Provide a deterministic stub namespace description."""

    return {
        "ns1": "stub-netns-1",
        "ns2": "stub-netns-2",
        "veth1": "stub-veth-1",
        "veth2": "stub-veth-2",
        "ip1": "192.0.2.1",
        "ip2": "192.0.2.2",
        "stubbed": True,
    }
