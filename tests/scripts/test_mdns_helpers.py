import sys
import textwrap
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from mdns_helpers import ensure_self_ad_is_visible  # noqa: E402


def _write_fixture(tmp_path, payload):
    path = tmp_path / "mdns.txt"
    path.write_text(textwrap.dedent(payload).strip() + "\n", encoding="utf-8")
    return path


def test_ensure_self_visible_matches_phase_and_host(tmp_path):
    fixture = _write_fixture(
        tmp_path,
        "=;eth0;IPv4;k3s-sugar-dev@host0 (bootstrap);_k3s-sugar-dev._tcp;local;host0.local;192.0.2.10;6443;"
        "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;txt=leader=host0.local;txt=phase=bootstrap",
    )

    ok, observed = ensure_self_ad_is_visible(
        expected_host="HOST0.LOCAL.",
        cluster="sugar",
        env="dev",
        retries=1,
        delay=0,
        require_phase="bootstrap",
        fixture_path=str(fixture),
    )

    assert ok is True
    assert observed == "host0.local"


def test_ensure_self_visible_requires_phase(tmp_path):
    fixture = _write_fixture(
        tmp_path,
        "=;eth0;IPv4;k3s-sugar-dev@host0 (bootstrap);_k3s-sugar-dev._tcp;local;host0.local;192.0.2.10;6443;"
        "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;txt=leader=host0.local;txt=phase=bootstrap",
    )

    ok, observed = ensure_self_ad_is_visible(
        expected_host="host0.local",
        cluster="sugar",
        env="dev",
        retries=2,
        delay=0,
        require_phase="server",
        fixture_path=str(fixture),
    )

    assert ok is False
    assert observed == "host0.local"


def test_ensure_self_visible_matches_leader(tmp_path):
    fixture = _write_fixture(
        tmp_path,
        "=;eth0;IPv4;k3s-sugar-dev@host1 (server);_k3s-sugar-dev._tcp;local;host1.local;192.0.2.11;6443;"
        "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;txt=leader=hostLeader.local;txt=phase=server",
    )

    ok, observed = ensure_self_ad_is_visible(
        expected_host="HOSTLEADER.LOCAL.",
        cluster="sugar",
        env="dev",
        retries=1,
        delay=0,
        require_phase="server",
        fixture_path=str(fixture),
    )

    assert ok is True
    assert observed == "hostLeader.local"
