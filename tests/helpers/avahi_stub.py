"""Utilities for enabling the hermetic Avahi CLI stub during pytest runs."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "avahi_stub"


def ensure_avahi_stub(tmp_path: Path, *, base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Expose the bundled Avahi stub when the real CLI tools are absent.

    The mdns_ready end-to-end suite now asserts discovery even when namespaces are simulated.
    This helper activates the stub binaries so tests keep running when the host lacks Avahi
    utilities or network namespace privileges.
    """

    tools = ("avahi-browse", "avahi-publish", "avahi-resolve", "avahi-resolve-host-name")
    env = base_env or os.environ
    force_stub = env.get("SUGARKUBE_FORCE_AVAHI_STUBS") == "1"

    if not force_stub and all(shutil.which(tool, path=env.get("PATH")) for tool in tools):
        # Nothing to do when the real tools are already available.
        return {}

    stub_dir = tmp_path / "avahi_stub"
    stub_dir.mkdir(parents=True, exist_ok=True)

    env_updates: dict[str, str] = {}

    if "AVAHI_STUB_DIR" not in env:
        env_updates["AVAHI_STUB_DIR"] = str(stub_dir)
    if "AVAHI_STUB_HOST" not in env:
        env_updates["AVAHI_STUB_HOST"] = "stub.local"
    if "AVAHI_STUB_IPV4" not in env:
        env_updates["AVAHI_STUB_IPV4"] = "127.0.0.1"
    if "AVAHI_AVAILABLE" not in env:
        env_updates["AVAHI_AVAILABLE"] = "1"

    env_updates["PATH"] = f"{FIXTURE_DIR}:{env.get('PATH', '')}"

    return env_updates
