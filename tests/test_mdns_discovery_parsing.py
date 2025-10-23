from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "k3s-discover.sh"


@pytest.fixture()
def mdns_env(tmp_path):
    fixture = tmp_path / "mdns.txt"
    fixture.write_text(
        "\n".join(
            [
                (
                    "=;eth0;IPv4;k3s API sugar/dev [bootstrap] on ctrl-0;_https._tcp;;ctrl-0;"
                    "192.168.50.9;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;"
                    "txt=role=bootstrap;txt=leader=ctrl-0.local;txt=state=pending"
                ),
                (
                    "=;eth0;IPv4;k3s API sugar/dev on ctrl-1;_https._tcp;local;ctrl-1.local;"
                    "192.168.50.10;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server"
                ),
                "=;eth0;IPv4;broken;_https._tcp;local;ctrl-2.local",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "SUGARKUBE_SERVERS": "1",
            "SUGARKUBE_NODE_TOKEN_PATH": str(tmp_path / "node-token"),
            "SUGARKUBE_BOOT_TOKEN_PATH": str(tmp_path / "boot-token"),
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_MDNS_FIXTURE_FILE": str(fixture),
        }
    )
    return env


def run_query(mode, env):
    result = subprocess.run(
        ["bash", str(SCRIPT), "--run-avahi-query", mode],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return [line for line in result.stdout.splitlines() if line]


def test_server_first_returns_expected_host(mdns_env):
    lines = run_query("server-first", mdns_env)
    assert lines == ["ctrl-1.local"]


def test_server_count_detects_single_server(mdns_env):
    lines = run_query("server-count", mdns_env)
    assert lines == ["1"]


def test_bootstrap_queries_include_domain_suffix(mdns_env):
    assert run_query("bootstrap-hosts", mdns_env) == ["ctrl-0.local"]
    assert run_query("bootstrap-leaders", mdns_env) == ["ctrl-0.local"]
