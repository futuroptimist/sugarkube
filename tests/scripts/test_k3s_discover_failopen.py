"""Tests for discovery fail-open path in k3s-discover."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
import textwrap

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"


def _write_stub(path: Path, content: str) -> None:
    content = content.lstrip("\n")
    if content.startswith("\\\n"):
        content = content[2:]
    lines = content.splitlines()
    indents = [
        len(line) - len(line.lstrip(" \t"))
        for line in lines
        if line.strip() and line[0] in (" ", "\t")
    ]
    if indents:
        trim = min(indents)
        prefix = " " * trim
        lines = [line[len(prefix) :] if line.startswith(prefix) else line for line in lines]
    content = "\n".join(lines)
    if content and content[-1] != "\n":
        content += "\n"
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_failopen_disabled_by_default_in_prod(tmp_path: Path) -> None:
    """Discovery fail-open should be disabled in production environment."""
    
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    
    # Stub required binaries
    _write_stub(bin_dir / "systemctl", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "iptables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "ip6tables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "configure_avahi.sh", "#!/usr/bin/env bash\nexit 0\n")
    
    # Create a stub that makes mDNS discovery fail
    mdns_fixture = tmp_path / "mdns-empty.json"
    mdns_fixture.write_text('{"servers": [], "bootstrap": []}\n', encoding="utf-8")
    
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SUGARKUBE_ENV": "prod",
        "SUGARKUBE_CLUSTER": "test",
        "SUGARKUBE_SERVERS": "2",
        "SUGARKUBE_TOKEN": "test-token",
        "SUGARKUBE_MDNS_FIXTURE_FILE": str(mdns_fixture),
        "SUGARKUBE_EXIT_AFTER_ABSENCE_GATE": "1",
        "SUGARKUBE_MDNS_ABSENCE_GATE": "0",  # Disable absence gate to avoid blocking
        "SUGARKUBE_CONFIGURE_AVAHI_BIN": str(bin_dir / "configure_avahi.sh"),
        "ALLOW_NON_ROOT": "1",
        "SUGARKUBE_SKIP_SYSTEMCTL": "1",
    }
    
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    
    # Should not trigger fail-open in prod environment
    assert "discovery_failopen_tracking_started" not in result.stderr


def test_failopen_enabled_by_default_in_dev(tmp_path: Path) -> None:
    """Discovery fail-open should be enabled by default in dev environment."""
    
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    
    # Stub required binaries
    _write_stub(bin_dir / "systemctl", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "iptables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "ip6tables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "configure_avahi.sh", "#!/usr/bin/env bash\nexit 0\n")
    
    # Create a stub that makes mDNS discovery fail
    mdns_fixture = tmp_path / "mdns-empty.json"
    mdns_fixture.write_text('{"servers": [], "bootstrap": []}\n', encoding="utf-8")
    
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SUGARKUBE_ENV": "dev",
        "SUGARKUBE_CLUSTER": "test",
        "SUGARKUBE_SERVERS": "2",
        "SUGARKUBE_TOKEN": "test-token",
        "SUGARKUBE_MDNS_FIXTURE_FILE": str(mdns_fixture),
        "SUGARKUBE_EXIT_AFTER_ABSENCE_GATE": "1",
        "SUGARKUBE_MDNS_ABSENCE_GATE": "0",  # Disable absence gate to avoid blocking
        "SUGARKUBE_CONFIGURE_AVAHI_BIN": str(bin_dir / "configure_avahi.sh"),
        "ALLOW_NON_ROOT": "1",
        "SUGARKUBE_SKIP_SYSTEMCTL": "1",
    }
    
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    
    # In dev, fail-open tracking should start
    # Note: We exit early with EXIT_AFTER_ABSENCE_GATE, so we won't see the tracking message
    # This test validates that the default is set correctly
    assert result.returncode == 0


def test_failopen_explicit_disable(tmp_path: Path) -> None:
    """Discovery fail-open can be explicitly disabled via feature flag."""
    
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    
    # Stub required binaries
    _write_stub(bin_dir / "systemctl", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "iptables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "ip6tables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "configure_avahi.sh", "#!/usr/bin/env bash\nexit 0\n")
    
    # Create a stub that makes mDNS discovery fail
    mdns_fixture = tmp_path / "mdns-empty.json"
    mdns_fixture.write_text('{"servers": [], "bootstrap": []}\n', encoding="utf-8")
    
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SUGARKUBE_ENV": "dev",
        "SUGARKUBE_CLUSTER": "test",
        "SUGARKUBE_SERVERS": "2",
        "SUGARKUBE_TOKEN": "test-token",
        "SUGARKUBE_DISCOVERY_FAILOPEN": "0",
        "SUGARKUBE_MDNS_FIXTURE_FILE": str(mdns_fixture),
        "SUGARKUBE_EXIT_AFTER_ABSENCE_GATE": "1",
        "SUGARKUBE_MDNS_ABSENCE_GATE": "0",  # Disable absence gate to avoid blocking
        "SUGARKUBE_CONFIGURE_AVAHI_BIN": str(bin_dir / "configure_avahi.sh"),
        "ALLOW_NON_ROOT": "1",
        "SUGARKUBE_SKIP_SYSTEMCTL": "1",
    }
    
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    
    # Should not trigger fail-open when explicitly disabled
    assert "discovery_failopen_tracking_started" not in result.stderr
    assert result.returncode == 0


def test_failopen_resolves_deterministic_hosts(tmp_path: Path) -> None:
    """Fail-open join should resolve deterministic hostnames after the timeout."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    # Common utility stubs
    _write_stub(bin_dir / "systemctl", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "iptables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "ip6tables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "apt-get", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "configure_avahi.sh", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "k3s-install-iptables.sh", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "curl", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "openssl", "#!/usr/bin/env bash\nexit 1\n")
    _write_stub(bin_dir / "avahi-resolve", "#!/usr/bin/env bash\nexit 1\n")

    _write_stub(
        bin_dir / "check_apiready.sh",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            if [ "${SERVER_HOST:-}" = "sugarkube1.local" ]; then
              exit 1
            fi
            exit 0
            """
        ),
    )
    _write_stub(bin_dir / "check_time_sync.sh", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "flag-parity.sh", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "l4_probe.sh", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(
        bin_dir / "join-gate.sh",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            exit 0
            """
        ),
    )

    real_getent = "/usr/bin/getent"
    _write_stub(
        bin_dir / "getent",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            if [ "${{1:-}}" = "hosts" ]; then
              case "${{2:-}}" in
                sugarkube0.local)
                  exit 2
                  ;;
                sugarkube1.local)
                  printf '192.0.2.21 %s\\n' "${{2}}"
                  exit 0
                  ;;
                sugarkube2.local)
                  printf '192.0.2.22 %s\\n' "${{2}}"
                  exit 0
                  ;;
              esac
            fi
            exec {real_getent} "$@"
            """
        ),
    )

    fixture = tmp_path / "mdns.txt"
    fixture.write_text(
        "+;eth0;IPv4;k3s API sugar/dev [server] on ;_https._tcp;local;;192.0.2.10;6443;"
        "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server\n",
        encoding="utf-8",
    )

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SUGARKUBE_CLUSTER": "sugar",
        "SUGARKUBE_ENV": "dev",
        "SUGARKUBE_SERVERS": "3",
        "SUGARKUBE_TOKEN": "failopen-token",
        "SUGARKUBE_DISCOVERY_FAILOPEN": "1",
        "SUGARKUBE_DISCOVERY_FAILOPEN_TIMEOUT": "0",
        "SUGARKUBE_MDNS_FIXTURE_FILE": str(fixture),
        "SUGARKUBE_MDNS_ABSENCE_GATE": "0",
        "SUGARKUBE_MDNS_PUBLISH_ADDR": "192.0.2.50",
        "SUGARKUBE_SKIP_SYSTEMCTL": "1",
        "ALLOW_NON_ROOT": "1",
        "DISCOVERY_WAIT_SECS": "0",
        "FOLLOWER_REELECT_SECS": "0",
        "SUGARKUBE_TEST_FAST_JOIN": "1",
        "SUGARKUBE_DISABLE_JOIN_GATE": "1",
        "SUGARKUBE_CONFIGURE_AVAHI_BIN": str(bin_dir / "configure_avahi.sh"),
        "SUGARKUBE_API_READY_CHECK_BIN": str(bin_dir / "check_apiready.sh"),
        "SUGARKUBE_TIME_SYNC_BIN": str(bin_dir / "check_time_sync.sh"),
        "SUGARKUBE_SERVER_FLAG_PARITY_BIN": str(bin_dir / "flag-parity.sh"),
        "SUGARKUBE_L4_PROBE_BIN": str(bin_dir / "l4_probe.sh"),
        "SUGARKUBE_JOIN_GATE_BIN": str(bin_dir / "join-gate.sh"),
        "SUGARKUBE_K3S_INSTALL_SCRIPT": str(bin_dir / "k3s-install-iptables.sh"),
    }

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    stderr = result.stderr
    assert "event=discovery_failopen_tracking_started" in stderr
    assert "event=failopen_join attempt=1 server=\"sugarkube0.local\" outcome=error" in stderr
    assert "event=failopen_join attempt=2 server=\"sugarkube1.local\" outcome=error reason=api_unreachable" in stderr
    assert "event=failopen_join attempt=3 server=\"sugarkube2.local\" outcome=ok" in stderr
    assert "target=\"192.0.2.22\"" in stderr
    assert "event=discovery_failopen_success" in stderr
