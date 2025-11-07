"""Tests for the k3s-discover mDNS helpers."""

# Developer note: RFC 6763 and 6762 expose instance names as display strings,
# so Avahi may emit spaces and punctuation between the label boundaries that DNS
# still enforces. The script calls `avahi-browse --parsable` to keep the
# semicolon field separators intact, ensuring tests exercise the same parsing
# path instead of relying on naive whitespace splits.

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "k3s-discover.sh"


@pytest.fixture()
def mdns_env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    browse = bin_dir / "avahi-browse"
    browse.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail

            if [[ "$#" -lt 4 || "$#" -gt 5 ]]; then
              echo "unexpected argument count: $#" >&2
              exit 1
            fi

            if [[ "$1" != "--parsable" || "$2" != "--terminate" ]]; then
              echo "unexpected arguments: $*" >&2
              exit 1
            fi

            shift 2

            if [[ "$1" != "--resolve" ]]; then
              echo "missing --resolve flag" >&2
              exit 1
            fi

            shift

            if [[ "$1" == "--ignore-local" ]]; then
              shift
            fi

            if [[ "$#" -ne 1 ]]; then
              echo "unexpected trailing arguments: $*" >&2
              exit 1
            fi

            service="$1"

            if [[ "$service" != "_k3s-sugar-dev._tcp" && "$service" != "_https._tcp" ]]; then
              echo "unexpected service type: $service" >&2
              exit 1
            fi

            printf '%s\n' \
              '=;eth0;IPv4;k3s-sugar-dev@sugar-control-0 (server);_k3s-sugar-dev._tcp;local;' \
              'sugar-control-0.local;192.168.50.10;6443;'\
              'txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server' \
              '=;eth0;IPv4;k3s-sugar-dev@sugar-control-1 (server);_k3s-sugar-dev._tcp;local;' \
              'sugar-control-1.local;192.168.50.11;6443;'\
              'txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server' \
              '=;eth0;IPv4;broken;_k3s-sugar-dev._tcp;local;sugar-control-2.local'
            """
        ),
        encoding="utf-8",
    )
    browse.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "SUGARKUBE_SERVERS": "1",
            "SUGARKUBE_NODE_TOKEN_PATH": str(tmp_path / "node-token"),
            "SUGARKUBE_BOOT_TOKEN_PATH": str(tmp_path / "boot-token"),
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_MDNS_DBUS": "0",
        }
    )
    return env


def run_query(mode: str, env: dict[str, str]) -> list[str]:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--run-avahi-query", mode],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    # DEBUG: Always print stderr to help diagnose Python 3.14 issues
    if result.stderr:
        print(f"\n=== STDERR from run_query('{mode}') ===\n{result.stderr}\n=== END STDERR ===\n", file=sys.stderr)
    assert result.returncode == 0, result.stderr
    return [line for line in result.stdout.splitlines() if line]


def test_server_first_returns_expected_host(mdns_env):
    lines = run_query("server-first", mdns_env)
    assert lines == ["sugar-control-0.local"]


def test_server_count_detects_all_servers(mdns_env):
    lines = run_query("server-count", mdns_env)
    assert lines == ["2"]


def test_bootstrap_queries_ignore_server_only_records(mdns_env):
    assert run_query("bootstrap-hosts", mdns_env) == []
    assert run_query("bootstrap-leaders", mdns_env) == []


def test_print_server_hosts_lists_unique_hosts(mdns_env):
    result = subprocess.run(
        ["bash", str(SCRIPT), "--print-server-hosts"],
        env=mdns_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "sugar-control-0.local",
        "sugar-control-1.local",
    ]
