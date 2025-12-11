"""Utilities for enabling the hermetic Avahi CLI stub during pytest runs."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "avahi_stub"


def ensure_avahi_stub(tmp_path: Path) -> None:
    """Expose the bundled Avahi stub when the real CLI tools are absent.

    The mdns_ready end-to-end suite documents a future plan to "provide an Avahi stub or fixture
    that guarantees local discovery succeeds." This helper activates the existing stub binaries
    so tests no longer skip when the host lacks Avahi utilities.
    """

    tools = ("avahi-browse", "avahi-publish", "avahi-resolve", "avahi-resolve-host-name")

    if all(shutil.which(tool) for tool in tools):
        # Nothing to do when the real tools are already available.
        return

    stub_dir = tmp_path / "avahi_stub"
    stub_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ
    env.setdefault("AVAHI_STUB_DIR", str(stub_dir))
    env.setdefault("AVAHI_STUB_HOST", "stub.local")
    env.setdefault("AVAHI_STUB_IPV4", "127.0.0.1")
    env.setdefault("AVAHI_AVAILABLE", "1")

    env["PATH"] = f"{FIXTURE_DIR}:{env['PATH']}"
