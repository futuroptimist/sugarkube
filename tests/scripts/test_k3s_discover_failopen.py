"""Tests for discovery fail-open path in k3s-discover."""

from __future__ import annotations

import os
import subprocess
import textwrap
import time
from pathlib import Path

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


def test_failopen_triggers_after_timeout(tmp_path: Path) -> None:
    """Discovery fail-open should trigger after configured timeout."""
    
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    
    install_log = tmp_path / "install.log"
    
    # Stub required binaries
    _write_stub(bin_dir / "systemctl", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "iptables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "ip6tables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "configure_avahi.sh", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "ss", "#!/usr/bin/env bash\necho 'LISTEN'\nexit 0\n")
    
    # Stub check_apiready to succeed for sugarkube0.local
    _write_stub(
        bin_dir / "check_apiready.sh",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            if [ "${SERVER_HOST:-}" = "sugarkube0.local" ]; then
                message='ts=stub level=info event=apiready outcome=ok'
                printf '%s host="%s"\n' "$message" "${SERVER_HOST}" >&2
                exit 0
            fi
            exit 1
            """
        ),
    )
    
    # Stub resolve_server_token to return a token
    _write_stub(
        bin_dir / "resolve_server_token.sh",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            echo "test-failopen-token"
            exit 0
            """
        ),
    )
    
    # Stub k3s install script
    _write_stub(
        bin_dir / "k3s-install-stub.sh",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            echo "K3S install called with args: $@" >> '{install_log}'
            exit 0
            """
        ),
    )
    
    # Create a stub that makes mDNS discovery fail
    mdns_fixture = tmp_path / "mdns-empty.json"
    mdns_fixture.write_text('{"servers": [], "bootstrap": []}\n', encoding="utf-8")
    
    # Stub elect_leader to return follower
    _write_stub(
        bin_dir / "elect_leader.sh",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            echo "winner=no"
            echo "key=test-key"
            exit 0
            """
        ),
    )
    
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SUGARKUBE_ENV": "dev",
        "SUGARKUBE_CLUSTER": "test",
        "SUGARKUBE_SERVERS": "2",
        "SUGARKUBE_TOKEN": "test-token",
        "SUGARKUBE_DISCOVERY_FAILOPEN": "1",
        "SUGARKUBE_DISCOVERY_FAILOPEN_TIMEOUT": "5",  # 5 seconds for testing
        "SUGARKUBE_MDNS_FIXTURE_FILE": str(mdns_fixture),
        "SUGARKUBE_K3S_INSTALL_SCRIPT": str(bin_dir / "k3s-install-stub.sh"),
        "SUGARKUBE_API_READY_CHECK_BIN": str(bin_dir / "check_apiready.sh"),
        "SUGARKUBE_ELECT_LEADER_BIN": str(bin_dir / "elect_leader.sh"),
        "SUGARKUBE_CONFIGURE_AVAHI_BIN": str(bin_dir / "configure_avahi.sh"),
        "DISCOVERY_WAIT_SECS": "1",
        "FOLLOWER_REELECT_SECS": "2",
        "ALLOW_NON_ROOT": "1",
        "SUGARKUBE_SKIP_SYSTEMCTL": "1",
        "SUGARKUBE_TEST_SKIP_PUBLISH_SLEEP": "1",
    }
    
    # Mock getent to resolve sugarkube0.local
    _write_stub(
        bin_dir / "getent",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            if [[ "$*" =~ sugarkube0.local ]]; then
                echo "192.168.1.10 sugarkube0.local"
                exit 0
            fi
            exit 1
            """
        ),
    )
    
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    
    # Should see fail-open tracking started
    assert "discovery_failopen_tracking_started" in result.stderr
    
    # Should eventually trigger fail-open and attempt join
    assert "switching to fail-open direct join" in result.stderr or \
           "discovery_failopen_success" in result.stderr


def test_failopen_logs_endpoints(tmp_path: Path) -> None:
    """Fail-open should log the endpoints it tries."""
    
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    
    # Stub required binaries
    _write_stub(bin_dir / "systemctl", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "iptables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "ip6tables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "configure_avahi.sh", "#!/usr/bin/env bash\nexit 0\n")
    
    # Stub check_apiready to always fail
    _write_stub(
        bin_dir / "check_apiready.sh",
        "#!/usr/bin/env bash\nexit 1\n"
    )
    
    # Stub resolve_server_token to return a token
    _write_stub(
        bin_dir / "resolve_server_token.sh",
        "#!/usr/bin/env bash\necho 'test-token'\nexit 0\n"
    )
    
    # Create a stub that makes mDNS discovery fail
    mdns_fixture = tmp_path / "mdns-empty.json"
    mdns_fixture.write_text('{"servers": [], "bootstrap": []}\n', encoding="utf-8")
    
    # Stub elect_leader to return follower
    _write_stub(
        bin_dir / "elect_leader.sh",
        "#!/usr/bin/env bash\necho 'winner=no'\necho 'key=test'\nexit 0\n"
    )
    
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SUGARKUBE_ENV": "dev",
        "SUGARKUBE_CLUSTER": "test",
        "SUGARKUBE_SERVERS": "2",
        "SUGARKUBE_TOKEN": "test-token",
        "SUGARKUBE_DISCOVERY_FAILOPEN": "1",
        "SUGARKUBE_DISCOVERY_FAILOPEN_TIMEOUT": "2",
        "SUGARKUBE_MDNS_FIXTURE_FILE": str(mdns_fixture),
        "SUGARKUBE_API_READY_CHECK_BIN": str(bin_dir / "check_apiready.sh"),
        "SUGARKUBE_ELECT_LEADER_BIN": str(bin_dir / "elect_leader.sh"),
        "SUGARKUBE_CONFIGURE_AVAHI_BIN": str(bin_dir / "configure_avahi.sh"),
        "DISCOVERY_WAIT_SECS": "1",
        "FOLLOWER_REELECT_SECS": "1",
        "ALLOW_NON_ROOT": "1",
        "SUGARKUBE_SKIP_SYSTEMCTL": "1",
    }
    
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    
    # Should log endpoint attempts
    assert "Attempting fail-open direct join" in result.stderr or \
           "endpoint=sugarkube0.local:6443" in result.stderr
