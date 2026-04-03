from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

SCRIPT = Path("scripts/tailscale_remote_ops.sh")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    path.chmod(0o755)


def test_up_uses_auth_key_file_and_extra_args(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "tailscale.log"
    auth_file = tmp_path / "auth.key"
    auth_file.write_text("tskey-auth-k8s-123\n", encoding="utf-8")

    _write_executable(
        bin_dir / "tailscaled",
        """
        #!/usr/bin/env bash
        exit 0
        """,
    )

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
        bin_dir / "tailscale",
        f"""
        #!/usr/bin/env bash
        set -euo pipefail
        echo "tailscale:$@" >> "{log}"
        exit 0
        """,
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [
            str(SCRIPT),
            "up",
            "--auth-key-file",
            str(auth_file),
            "--accept-routes",
            "--extra-arg",
            "--ssh",
            "--extra-arg",
            "--advertise-tags=tag:ops",
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    content = log.read_text(encoding="utf-8")
    assert "tailscale:up --auth-key tskey-auth-k8s-123 --accept-routes --ssh --advertise-tags=tag:ops" in content


def test_up_rejects_missing_auth_env_value(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    for name in ("tailscale", "tailscaled", "sudo"):
        _write_executable(
            bin_dir / name,
            """
            #!/usr/bin/env bash
            exit 0
            """,
        )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env.pop("TS_AUTHKEY", None)

    result = subprocess.run(
        [str(SCRIPT), "up", "--auth-key-env", "TS_AUTHKEY"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "TS_AUTHKEY is empty or unset" in result.stderr


def test_status_json_forwards_flag(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "status.log"

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
        if [ "$1" = "status" ] && [ "$2" = "--json" ]; then
            printf '%s\n' '{{"BackendState":"Running"}}'
            exit 0
        fi
        exit 1
        """,
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [str(SCRIPT), "status", "--json"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert '"BackendState":"Running"' in result.stdout
    assert "tailscale:status --json" in log.read_text(encoding="utf-8")
