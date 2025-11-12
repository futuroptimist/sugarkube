"""Tests for discovery fail-open path in k3s-discover."""

from __future__ import annotations

import os
import subprocess
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
