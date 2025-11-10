from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "mdns_selfcheck.sh"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"


def _write_stub(path: Path, *lines: str) -> None:
    path.write_text("".join(lines), encoding="utf-8")
    path.chmod(0o755)


def test_resolution_warn_emits_reason(tmp_path: Path) -> None:
    """mdns_resolution_status warn events should include the failure reason."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    main_fixture = FIXTURES_DIR / "avahi_browse_agent_ok.txt"
    services_fixture = FIXTURES_DIR / "avahi_browse_services_with_k3s.txt"

    _write_stub(
        bin_dir / "avahi-browse",
        "#!/usr/bin/env bash\n",
        "set -euo pipefail\n",
        "last=\"\"\n",
        "if [ \"$#\" -gt 0 ]; then\n",
        "  last=\"${!#}\"\n",
        "fi\n",
        "if [ \"${last}\" = \"_services._dns-sd._udp\" ]; then\n",
        f"  cat '{services_fixture}'\n",
        "  exit 0\n",
        "fi\n",
        f"cat '{main_fixture}'\n",
    )
    _write_stub(bin_dir / "avahi-resolve", "#!/usr/bin/env bash\nexit 1\n")
    _write_stub(bin_dir / "avahi-resolve-host-name", "#!/usr/bin/env bash\nexit 1\n")
    _write_stub(bin_dir / "getent", "#!/usr/bin/env bash\nexit 2\n")
    _write_stub(bin_dir / "curl", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "systemctl", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "busctl", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "gdbus", "#!/usr/bin/env bash\nexit 127\n")
    _write_stub(
        bin_dir / "hostname",
        "#!/usr/bin/env bash\n",
        "if [ \"${1:-}\" = '-s' ]; then\n",
        "  printf '%s\\n' sugarkube0\n",
        "  exit 0\n",
        "fi\n",
        "printf '%s\\n' sugarkube0.local\n",
    )
    _write_stub(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "ALLOW_NON_ROOT": "1",
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_EXPECTED_HOST": "sugarkube0.local",
            "SUGARKUBE_EXPECTED_IPV4": "192.168.3.10",
            "SUGARKUBE_EXPECTED_ROLE": "agent",
            "SUGARKUBE_EXPECTED_PHASE": "agent",
            "SUGARKUBE_SELFCHK_ATTEMPTS": "1",
            "SUGARKUBE_SELFCHK_BACKOFF_START_MS": "0",
            "SUGARKUBE_SELFCHK_BACKOFF_CAP_MS": "0",
            "SUGARKUBE_MDNS_DBUS": "0",
            "LOG_LEVEL": "debug",
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    status_lines = [
        line for line in result.stdout.splitlines() if "event=mdns_resolution_status" in line
    ]
    assert status_lines, result.stdout
    status_line = status_lines[-1]
    assert "outcome=warn" in status_line
    assert ("reason=resolve_failed" in status_line) or ("reason=\"resolve_failed\"" in status_line)
