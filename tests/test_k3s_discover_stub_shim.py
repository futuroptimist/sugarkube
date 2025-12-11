"""Ensure the Avahi browse shim backfills environments without avahi-browse installed."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_k3s_discover_failopen_e2e import _create_stub_bin


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required for stub execution")
def test_create_stub_bin_inlines_avahi_shim_when_missing(monkeypatch, tmp_path: Path):
    real_which = shutil.which

    def fake_which(binary: str):
        if binary == "avahi-browse":
            return None
        return real_which(binary)

    monkeypatch.setattr(shutil, "which", fake_which)

    stubs = _create_stub_bin(
        tmp_path,
        canonical_host="sugarkube-leader.local",
        fallback_host="sugarkube0.local",
        leader_ip="192.168.120.1",
    )

    avahi_stub = stubs["avahi_browse"]
    env = {
        "AVAHI_STUB_MODE": "real",
        "SUGARKUBE_CLUSTER": "sugar",
        "SUGARKUBE_ENV": "dev",
    }
    real_result = subprocess.run(
        [str(avahi_stub), "--parsable", "--resolve", "_k3s-sugar-dev._tcp"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert real_result.returncode == 0
    assert "sugarkube-leader.local" in real_result.stdout
    assert "_k3s-sugar-dev._tcp" in real_result.stdout

    fail_result = subprocess.run(
        [str(avahi_stub), "--parsable", "--resolve", "_k3s-sugar-dev._tcp"],
        capture_output=True,
        text=True,
        check=False,
        env={**env, "AVAHI_STUB_MODE": "fail"},
    )

    assert fail_result.returncode != 0
    assert "stub forcing failure" in fail_result.stderr
