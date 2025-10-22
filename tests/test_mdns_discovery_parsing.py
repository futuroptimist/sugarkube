import os
import shlex
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "k3s-discover.sh"


@pytest.fixture()
def mdns_env(tmp_path):
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()

    avahi_stub = stub_dir / "avahi-browse"
    avahi_stub.write_text(
        (
            "#!/usr/bin/env bash\n"
            "cat <<'EOF'\n"
            "=;wlan0;IPv4;k3s API sugar/dev on pi1;_https._tcp;local;pi1.local;pi1.local;6443;"
            "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server\n"
            "EOF\n"
        ),
        encoding="utf-8",
    )
    avahi_stub.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{stub_dir}:{env['PATH']}"
    env.setdefault("SUGARKUBE_CLUSTER", "sugar")
    env.setdefault("SUGARKUBE_ENV", "dev")
    return env


def _run_function(function: str, env: dict) -> subprocess.CompletedProcess:
    command = (
        f"source {shlex.quote(str(SCRIPT))}"
        f" && run_avahi_query {shlex.quote(function)}"
    )
    return subprocess.run(
        ["bash", "-c", command],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_server_first_returns_host(mdns_env):
    result = _run_function("server-first", mdns_env)

    assert result.returncode == 0
    assert result.stdout.strip() == "pi1.local"


def test_server_count_reports_single_host(mdns_env):
    result = _run_function("server-count", mdns_env)

    assert result.returncode == 0
    assert result.stdout.strip() == "1"


def test_bootstrap_queries_empty_when_only_server(mdns_env):
    hosts = _run_function("bootstrap-hosts", mdns_env)
    leaders = _run_function("bootstrap-leaders", mdns_env)

    assert hosts.returncode == 0
    assert hosts.stdout.strip() == ""

    assert leaders.returncode == 0
    assert leaders.stdout.strip() == ""
