from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "tailscale_remote_ops.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_status_reports_running_backend(tmp_path: Path) -> None:
    fakebin = tmp_path / "bin"
    fakebin.mkdir()

    tailscale = fakebin / "tailscale"
    _write_executable(
        tailscale,
        """#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = "status" ] && [ "${2:-}" = "--json" ]; then
  cat <<'JSON'
{"BackendState":"Running","Self":{"HostName":"sugarkube0","TailscaleIPs":["100.100.100.10"]}}
JSON
  exit 0
fi
exit 1
""",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fakebin}:{env.get('PATH', '')}"

    result = subprocess.run(
        ["bash", str(SCRIPT), "status"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "BackendState=Running" in result.stdout
    assert "HostName=sugarkube0" in result.stdout


def test_status_fails_when_backend_not_running(tmp_path: Path) -> None:
    fakebin = tmp_path / "bin"
    fakebin.mkdir()

    tailscale = fakebin / "tailscale"
    _write_executable(
        tailscale,
        """#!/usr/bin/env bash
set -euo pipefail
cat <<'JSON'
{"BackendState":"Stopped","Self":{"HostName":"sugarkube0","TailscaleIPs":[]}}
JSON
""",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fakebin}:{env.get('PATH', '')}"

    result = subprocess.run(
        ["bash", str(SCRIPT), "status"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "not running" in result.stderr


def test_up_uses_auth_key_when_present(tmp_path: Path) -> None:
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    calls = tmp_path / "calls.log"

    _write_executable(
        fakebin / "sudo",
        """#!/usr/bin/env bash
set -euo pipefail
exec "$@"
""",
    )
    _write_executable(
        fakebin / "tailscale",
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "{calls}"
""",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fakebin}:{env.get('PATH', '')}"
    env["SUGARKUBE_TAILSCALE_AUTH_KEY"] = "tskey-auth-kid"

    result = subprocess.run(
        ["bash", str(SCRIPT), "up", "--ssh"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    logged = calls.read_text(encoding="utf-8")
    assert "up --auth-key tskey-auth-kid --ssh" in logged


def test_install_rejects_unsafe_override_url(tmp_path: Path) -> None:
    fakebin = tmp_path / "bin"
    fakebin.mkdir()

    _write_executable(
        fakebin / "curl",
        """#!/usr/bin/env bash
set -euo pipefail
exit 0
""",
    )
    _write_executable(
        fakebin / "sh",
        """#!/usr/bin/env bash
set -euo pipefail
exit 0
""",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fakebin}:{env.get('PATH', '')}"
    env["SUGARKUBE_TAILSCALE_INSTALL_URL"] = "https://example.test/'; touch /tmp/pwn #"

    result = subprocess.run(
        ["bash", str(SCRIPT), "install"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "contains unsafe characters" in result.stderr
