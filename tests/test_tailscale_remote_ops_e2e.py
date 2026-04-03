from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("ensure_just_available")



def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    path.chmod(0o755)


def test_just_tailscale_up_and_status_with_auth_file(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.log"
    auth_file = tmp_path / "tailscale.auth"
    auth_file.write_text("tskey-e2e-abc\n", encoding="utf-8")

    _write_executable(
        bin_dir / "sudo",
        f"""
        #!/usr/bin/env bash
        set -euo pipefail
        echo "sudo:$@" >> "{log}"
        exec "$@"
        """,
    )

    _write_executable(
        bin_dir / "tailscaled",
        """
        #!/usr/bin/env bash
        exit 0
        """,
    )

    _write_executable(
        bin_dir / "tailscale",
        f"""
        #!/usr/bin/env bash
        set -euo pipefail
        echo "tailscale:$@" >> "{log}"
        if [ "$1" = "status" ]; then
            if [ "${{2-}}" = "--json" ]; then
                printf '%s\n' '{{"BackendState":"Running","Self":{{"HostName":"sugarkube0"}}}}'
            else
                printf '%s\n' '100.64.0.10 sugarkube0 linux active; direct 203.0.113.9:41641'
            fi
            exit 0
        fi
        exit 0
        """,
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    up = subprocess.run(
        ["just", "--justfile", "justfile", "tailscale-up", f"auth_key_file={auth_file}"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert up.returncode == 0, up.stderr

    status = subprocess.run(
        ["just", "--justfile", "justfile", "tailscale-status"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert status.returncode == 0, status.stderr
    assert 'sugarkube0' in status.stdout

    log_data = log.read_text(encoding="utf-8")
    assert "tailscale:up --auth-key tskey-e2e-abc" in log_data
    assert "tailscale:status" in log_data
