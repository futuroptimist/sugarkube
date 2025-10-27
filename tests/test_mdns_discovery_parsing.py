import os
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "k3s-discover.sh"


@pytest.fixture()
def mdns_env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    browse = bin_dir / "avahi-browse"
    browse.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -lt 4 ]]; then
  echo "unexpected argument count: $#" >&2
  exit 1
fi

if [[ "$1" != "--parsable" || "$2" != "--terminate" ]]; then
  echo "unexpected arguments: $*" >&2
  exit 1
fi

shift 2
if [[ "$1" != "--resolve" ]]; then
  echo "missing --resolve: $*" >&2
  exit 1
fi

shift
if [[ "$1" == "--ignore-local" ]]; then
  shift
fi

if [[ "$#" -ne 1 ]]; then
  echo "unexpected leftover arguments: $*" >&2
  exit 1
fi

if [[ "$1" != "_https._tcp" ]]; then
  echo "unexpected service type: $1" >&2
  exit 1
fi

cat <<'EOF'
=;eth0;IPv4;k3s API sugar/dev on ctrl-1;_https._tcp;local;sugar-control-0.local;192.168.50.10;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server
=;eth0;IPv4;k3s API sugar/dev on ctrl-2;_https._tcp;local;sugar-control-1.local;192.168.50.11;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server
=;eth0;IPv4;broken;_https._tcp;local;sugar-control-2.local
EOF
""",
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
    assert lines == ["sugar-control-0.local"]


def test_server_count_detects_single_server(mdns_env):
    lines = run_query("server-count", mdns_env)
    assert lines == ["2"]


def test_server_hosts_lists_unique_servers(mdns_env):
    lines = run_query("server-hosts", mdns_env)
    assert lines == ["sugar-control-0.local", "sugar-control-1.local"]


def test_bootstrap_queries_ignore_server_only_records(mdns_env):
    assert run_query("bootstrap-hosts", mdns_env) == []
    assert run_query("bootstrap-leaders", mdns_env) == []
