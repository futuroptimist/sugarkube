"""Tests for discovery fail-open timeout configuration."""

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


def test_failopen_timeout_is_60_seconds_for_dev(tmp_path: Path) -> None:
    """Discovery fail-open timeout should be 60 seconds in dev environment."""
    
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    
    # Stub required binaries
    _write_stub(bin_dir / "systemctl", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "iptables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "ip6tables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "configure_avahi.sh", "#!/usr/bin/env bash\nexit 0\n")
    
    # Create a test wrapper that extracts the timeout value
    test_wrapper = tmp_path / "test_wrapper.sh"
    test_wrapper.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail

# Source the script to access variables
ALLOW_NON_ROOT=1
SUGARKUBE_ENV=dev
SUGARKUBE_CLUSTER=test
SUGARKUBE_SERVERS=2
SUGARKUBE_EXIT_AFTER_ABSENCE_GATE=1
SUGARKUBE_MDNS_ABSENCE_GATE=0
SUGARKUBE_CONFIGURE_AVAHI_BIN={bin_dir}/configure_avahi.sh
SUGARKUBE_SKIP_SYSTEMCTL=1

source {SCRIPT}

# Print the timeout value
echo "DISCOVERY_FAILOPEN_TIMEOUT_SECS=${{DISCOVERY_FAILOPEN_TIMEOUT_SECS}}"
""",
        encoding="utf-8"
    )
    test_wrapper.chmod(0o755)
    
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }
    
    result = subprocess.run(
        ["bash", str(test_wrapper)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    
    # Should show 60 seconds for dev
    assert "DISCOVERY_FAILOPEN_TIMEOUT_SECS=60" in result.stdout


def test_failopen_timeout_is_300_seconds_for_prod(tmp_path: Path) -> None:
    """Discovery fail-open timeout should be 300 seconds in prod environment."""
    
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    
    # Stub required binaries
    _write_stub(bin_dir / "systemctl", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "iptables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "ip6tables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "configure_avahi.sh", "#!/usr/bin/env bash\nexit 0\n")
    
    # Create a test wrapper that extracts the timeout value
    test_wrapper = tmp_path / "test_wrapper.sh"
    test_wrapper.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail

# Source the script to access variables
ALLOW_NON_ROOT=1
SUGARKUBE_ENV=prod
SUGARKUBE_CLUSTER=test
SUGARKUBE_SERVERS=2
SUGARKUBE_EXIT_AFTER_ABSENCE_GATE=1
SUGARKUBE_MDNS_ABSENCE_GATE=0
SUGARKUBE_CONFIGURE_AVAHI_BIN={bin_dir}/configure_avahi.sh
SUGARKUBE_SKIP_SYSTEMCTL=1

source {SCRIPT}

# Print the timeout value
echo "DISCOVERY_FAILOPEN_TIMEOUT_SECS=${{DISCOVERY_FAILOPEN_TIMEOUT_SECS}}"
""",
        encoding="utf-8"
    )
    test_wrapper.chmod(0o755)
    
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }
    
    result = subprocess.run(
        ["bash", str(test_wrapper)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    
    # Should show 300 seconds for prod
    assert "DISCOVERY_FAILOPEN_TIMEOUT_SECS=300" in result.stdout


def test_failopen_timeout_can_be_overridden(tmp_path: Path) -> None:
    """Discovery fail-open timeout should respect SUGARKUBE_DISCOVERY_FAILOPEN_TIMEOUT."""
    
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    
    # Stub required binaries
    _write_stub(bin_dir / "systemctl", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "iptables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "ip6tables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "configure_avahi.sh", "#!/usr/bin/env bash\nexit 0\n")
    
    # Create a test wrapper that extracts the timeout value
    test_wrapper = tmp_path / "test_wrapper.sh"
    test_wrapper.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail

# Source the script to access variables
ALLOW_NON_ROOT=1
SUGARKUBE_ENV=dev
SUGARKUBE_CLUSTER=test
SUGARKUBE_SERVERS=2
SUGARKUBE_EXIT_AFTER_ABSENCE_GATE=1
SUGARKUBE_MDNS_ABSENCE_GATE=0
SUGARKUBE_CONFIGURE_AVAHI_BIN={bin_dir}/configure_avahi.sh
SUGARKUBE_SKIP_SYSTEMCTL=1
SUGARKUBE_DISCOVERY_FAILOPEN_TIMEOUT=42

source {SCRIPT}

# Print the timeout value
echo "DISCOVERY_FAILOPEN_TIMEOUT_SECS=${{DISCOVERY_FAILOPEN_TIMEOUT_SECS}}"
""",
        encoding="utf-8"
    )
    test_wrapper.chmod(0o755)
    
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }
    
    result = subprocess.run(
        ["bash", str(test_wrapper)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    
    # Should show the custom value
    assert "DISCOVERY_FAILOPEN_TIMEOUT_SECS=42" in result.stdout
