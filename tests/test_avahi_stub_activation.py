"""Guardrails around the Avahi stub activation helper."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from tests.helpers.avahi_stub import ensure_avahi_stub


def test_avahi_stub_enables_cli_tools_when_missing(tmp_path, monkeypatch) -> None:
    """The helper should satisfy mdns_ready's CLI needs without system Avahi packages."""

    monkeypatch.setenv("PATH", "")

    ensure_avahi_stub(tmp_path)

    for tool in ("avahi-browse", "avahi-publish", "avahi-resolve", "avahi-resolve-host-name"):
        assert shutil.which(tool), f"{tool} should be available after enabling the stub"

    state_dir = Path(os.environ["AVAHI_STUB_DIR"]).expanduser()
    assert state_dir.exists(), "Stub helper should provision a writable state directory"
