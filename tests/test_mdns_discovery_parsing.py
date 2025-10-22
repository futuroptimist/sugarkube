from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "k3s-discover.sh"


@pytest.fixture()
def mdns_env(tmp_path: Path) -> dict[str, str]:
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()

    avahi_stub = stub_dir / "avahi-browse"
    avahi_stub.write_text(
        """#!/usr/bin/env bash
cat <<'OUT'
=;eth0;IPv4;k3s API sugar/dev on pi1;_https._tcp;local;pi1.local;192.168.1.10;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server
OUT
""",
        encoding="utf-8",
    )
    avahi_stub.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "PATH": f"{stub_dir}:{env['PATH']}",
        }
    )
    return env


def _call_function(function: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    command = (
        f"source {shlex.quote(str(SCRIPT))} && "
        f"{function}"
    )
    return subprocess.run(
        ["bash", "-c", command],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )


def test_server_first_returns_primary_host(mdns_env: dict[str, str]) -> None:
    result = _call_function("run_avahi_query server-first", mdns_env)
    assert result.stdout.strip() == "192.168.1.10"


def test_server_count_reports_one(mdns_env: dict[str, str]) -> None:
    result = _call_function("run_avahi_query server-count", mdns_env)
    assert result.stdout.strip() == "1"


def test_bootstrap_queries_empty_when_only_server(mdns_env: dict[str, str]) -> None:
    result_hosts = _call_function("run_avahi_query bootstrap-hosts", mdns_env)
    assert result_hosts.stdout.strip() == ""

    result_leaders = _call_function("run_avahi_query bootstrap-leaders", mdns_env)
    assert result_leaders.stdout.strip() == ""
