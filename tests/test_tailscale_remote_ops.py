from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "tailscale_remote_ops.sh"
JUSTFILE_PATH = REPO_ROOT / "justfile"

pytestmark = pytest.mark.usefixtures("ensure_just_available")


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def test_justfile_tailscale_recipes_use_helper_script() -> None:
    text = JUSTFILE_PATH.read_text(encoding="utf-8")

    assert '"{{ scripts_dir }}/tailscale_remote_ops.sh" install' in text
    assert '"{{ scripts_dir }}/tailscale_remote_ops.sh" up' in text
    assert '"{{ scripts_dir }}/tailscale_remote_ops.sh" status' in text
    assert "tailscale.com/install.sh | sh" not in text


def test_tailscale_install_dry_run_reports_install_url() -> None:
    result = subprocess.run(
        [str(SCRIPT_PATH), "install"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env={**os.environ, "TAILSCALE_DRY_RUN": "1", "TAILSCALE_INSTALL_URL": "https://example.invalid/install.sh"},
        check=False,
    )

    assert result.returncode == 0
    assert "https://example.invalid/install.sh" in result.stderr


def test_tailscale_up_uses_auth_key_file_and_redacts_in_dry_run(tmp_path: Path) -> None:
    key_file = tmp_path / "auth.key"
    key_file.write_text("tskey-auth-abc123\n", encoding="utf-8")

    _write_exec(
        tmp_path / "tailscale",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "exit 0\n",
    )

    result = subprocess.run(
        [str(SCRIPT_PATH), "up", "--ssh", "--accept-dns=false"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "TAILSCALE_DRY_RUN": "1",
            "TAILSCALE_AUTH_KEY_FILE": str(key_file),
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
        },
        check=False,
    )

    assert result.returncode == 0
    assert "redacted" in result.stderr
    assert "tskey-auth-abc123" not in result.stderr


def test_tailscale_status_recipe_e2e_with_stubs(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "commands.log"

    _write_exec(
        bin_dir / "tailscale",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo tailscale:$@ >> '{log_path}'\n"
        "if [ \"${1:-}\" = \"status\" ]; then\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
    )

    result = subprocess.run(
        ["just", "tailscale-status", "--peers=false"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        check=False,
    )

    assert result.returncode == 0, result.stderr
    logged = log_path.read_text(encoding="utf-8")
    assert "tailscale:status --peers=false" in logged


def test_tailscale_up_recipe_e2e_invokes_sudo_and_up(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "commands.log"

    _write_exec(
        bin_dir / "sudo",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo sudo:$@ >> '{log_path}'\n"
        "exec \"$@\"\n",
    )
    _write_exec(
        bin_dir / "tailscale",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo tailscale:$@ >> '{log_path}'\n"
        "exit 0\n",
    )

    result = subprocess.run(
        ["just", "tailscale-up", "tskey-auth-placeholder", "--ssh"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        check=False,
    )

    assert result.returncode == 0, result.stderr
    logged = log_path.read_text(encoding="utf-8")
    assert "tailscale:up --auth-key tskey-auth-placeholder --ssh" in logged
