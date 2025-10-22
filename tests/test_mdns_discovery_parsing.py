import os
import subprocess
import textwrap
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "k3s-discover.sh"

AVAHI_SAMPLE = textwrap.dedent(
    """
    +;eth0;IPv4;Other Service;_http._tcp;local;other.local;192.168.0.30;80;txt=foo=bar
    @;lo;IPv4;Short
    =;eth0;IPv4;k3s API sugar/dev on control;_https._tcp;local;control.local;192.168.0.10;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server
    """
).strip()


def _build_env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    avahi_stub = bin_dir / "avahi-browse"
    avahi_stub.write_text(
        "#!/bin/sh\n"
        "cat <<'EOF'\n"
        f"{AVAHI_SAMPLE}\n"
        "EOF\n"
    )
    avahi_stub.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["SUGARKUBE_TOKEN"] = "dummy-token"
    env.pop("SUGARKUBE_DEBUG", None)
    return env


def _run_query(tmp_path, mode):
    env = _build_env(tmp_path)
    result = subprocess.run(
        [str(SCRIPT), "--run-avahi-query", mode],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    output = result.stdout.strip()
    return output.splitlines() if output else []


def test_server_first_returns_control_host(tmp_path):
    lines = _run_query(tmp_path, "server-first")
    assert lines == ["192.168.0.10"]


def test_server_count_detects_single_host(tmp_path):
    lines = _run_query(tmp_path, "server-count")
    assert lines == ["1"]


def test_bootstrap_queries_empty_when_only_server(tmp_path):
    hosts = _run_query(tmp_path, "bootstrap-hosts")
    leaders = _run_query(tmp_path, "bootstrap-leaders")
    assert hosts == []
    assert leaders == []
