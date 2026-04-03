"""Tests for scripts/tailscale_remote_ops.sh."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "tailscale_remote_ops.sh"


def _write_stub(stub_dir: Path, name: str, body: str) -> None:
    path = stub_dir / name
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _run(
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [str(SCRIPT), *args],
        cwd=REPO_ROOT,
        env=merged_env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_up_uses_interactive_login_when_no_authkey(tmp_path: Path) -> None:
    calls = tmp_path / "calls.log"
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()

    _write_stub(
        stub_dir,
        "sudo",
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" > {calls}\n",
    )
    _write_stub(stub_dir, "tailscale", "#!/usr/bin/env bash\nexit 0\n")

    result = _run("up", env={"PATH": f"{stub_dir}:{os.environ['PATH']}"})

    assert result.returncode == 0, result.stderr
    assert calls.read_text(encoding="utf-8").strip() == "tailscale up"


def test_up_reads_authkey_from_file(tmp_path: Path) -> None:
    calls = tmp_path / "calls.log"
    authkey_path = tmp_path / "authkey.txt"
    authkey_path.write_text("tskey-auth-abc123\n", encoding="utf-8")

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    _write_stub(
        stub_dir,
        "sudo",
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" > {calls}\n",
    )
    _write_stub(stub_dir, "tailscale", "#!/usr/bin/env bash\nexit 0\n")

    result = _run(
        "up",
        "--",
        "--ssh",
        env={
            "PATH": f"{stub_dir}:{os.environ['PATH']}",
            "TS_AUTHKEY_FILE": str(authkey_path),
        },
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text(encoding="utf-8").strip() == "tailscale up --auth-key tskey-auth-abc123 --ssh"


def test_up_rejects_conflicting_authkey_inputs(tmp_path: Path) -> None:
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    _write_stub(stub_dir, "sudo", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(stub_dir, "tailscale", "#!/usr/bin/env bash\nexit 0\n")

    authkey_path = tmp_path / "authkey.txt"
    authkey_path.write_text("tskey-auth-file\n", encoding="utf-8")

    result = _run(
        "up",
        env={
            "PATH": f"{stub_dir}:{os.environ['PATH']}",
            "TS_AUTHKEY": "tskey-auth-env",
            "TS_AUTHKEY_FILE": str(authkey_path),
        },
    )

    assert result.returncode != 0
    assert "set only one of TS_AUTHKEY or TS_AUTHKEY_FILE" in result.stderr


def test_justfile_tailscale_recipes_delegate_to_script() -> None:
    content = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    assert "tailscale-install:" in content
    assert "bash scripts/tailscale_remote_ops.sh install" in content
    assert "tailscale-up extra_args=''" in content
    assert "bash scripts/tailscale_remote_ops.sh up" in content
    assert "tailscale-status extra_args=''" in content
    assert "bash scripts/tailscale_remote_ops.sh status" in content
