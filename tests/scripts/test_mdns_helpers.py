import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from mdns_helpers import ensure_self_ad_is_visible  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_fixture_env(monkeypatch):
    monkeypatch.delenv("SUGARKUBE_MDNS_FIXTURE_FILE", raising=False)
    yield
    monkeypatch.delenv("SUGARKUBE_MDNS_FIXTURE_FILE", raising=False)


def test_ensure_self_ad_filters_by_phase_and_leader(tmp_path, monkeypatch):
    fixture = tmp_path / "records.txt"
    fixture.write_text(
        "=;eth0;IPv4;k3s-sugar-dev@host0 (server);_k3s-sugar-dev._tcp;local;host0.local;"
        "192.168.1.10;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;"
        "txt=leader=host0.local;txt=phase=server\n"
        "=;eth0;IPv4;k3s-sugar-dev@candidate (bootstrap);_k3s-sugar-dev._tcp;local;candidate.local;"
        "192.168.1.11;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
        "txt=leader=leader-host.local.;txt=phase=bootstrap;txt=state=pending\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("SUGARKUBE_MDNS_FIXTURE_FILE", str(fixture))

    ok, observed = ensure_self_ad_is_visible(
        expected_host="host0.LOCAL.",
        cluster="sugar",
        env="dev",
        require_phase="server",
        retries=1,
        delay=0,
    )
    assert ok
    assert observed == "host0.local"

    ok, observed = ensure_self_ad_is_visible(
        expected_host="leader-host.local",
        cluster="sugar",
        env="dev",
        require_phase="bootstrap",
        retries=1,
        delay=0,
    )
    assert ok
    assert observed == "leader-host.local"

    ok, _ = ensure_self_ad_is_visible(
        expected_host="missing.local",
        cluster="sugar",
        env="dev",
        require_phase="server",
        retries=1,
        delay=0,
    )
    assert not ok
