from __future__ import annotations

import os
import stat
import pwd
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest


def _run_as(
    user: str,
    command: str,
    *,
    cwd: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess:
    runner = shutil.which("runuser")
    if runner:
        cmd = [runner, "-u", user, "--", "bash", "-c", command]
    else:
        cmd = ["su", "--preserve-environment", user, "-s", "/bin/bash", "-c", command]
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
@pytest.mark.skipif(
    getattr(os, "geteuid", lambda: 0)() != 0, reason="requires root privileges"
)
def test_fix_permissions_allows_non_root_collect(tmp_path: Path) -> None:
    if shutil.which("runuser") is None and shutil.which("su") is None:
        pytest.skip("runuser/su utilities not available")

    repo_root = Path(__file__).resolve().parents[1]
    collect_script = repo_root / "scripts" / "collect_pi_image.sh"
    fix_script = repo_root / "scripts" / "fix_pi_image_permissions.sh"

    nobody = pwd.getpwnam("nobody")
    original_permissions: list[tuple[Path, int, int, int]] = []

    def _record_and_set(path: Path, *, uid: int, gid: int, mode: int) -> None:
        stat_result = path.stat()
        original_permissions.append(
            (path, stat_result.st_uid, stat_result.st_gid, stat.S_IMODE(stat_result.st_mode))
        )
        os.chown(path, uid, gid)
        os.chmod(path, mode)

    paths_to_adjust = [tmp_path.parent.parent, tmp_path.parent, tmp_path]

    try:
        for parent in paths_to_adjust:
            _record_and_set(parent, uid=nobody.pw_uid, gid=nobody.pw_gid, mode=0o775)

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _record_and_set(workspace, uid=nobody.pw_uid, gid=nobody.pw_gid, mode=0o775)

        deploy = workspace / "deploy"
        deploy.mkdir()
        _record_and_set(deploy, uid=nobody.pw_uid, gid=nobody.pw_gid, mode=0o775)
        raw_img = deploy / "example.img"
        raw_img.write_text("payload", encoding="utf-8")

        out_path = workspace / "sugarkube.img.xz"

        env = os.environ.copy()
        env["XZ_OPT"] = "-T0 -0"
        result = subprocess.run(
            ["/bin/bash", str(collect_script), str(deploy), str(out_path)],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.returncode == 0

        # Files should be owned by root (uid 0) after the initial run.
        assert out_path.stat().st_uid == 0
        checksum_path = out_path.with_suffix(out_path.suffix + ".sha256")
        assert checksum_path.exists()
        assert checksum_path.stat().st_uid == 0

        user_env = {
            "HOME": str(workspace / "nobody-home"),
            "TMPDIR": str(workspace / "nobody-tmp"),
            "PATH": os.environ["PATH"],
            "USER": "nobody",
            "XZ_OPT": "-T0 -0",
        }
        Path(user_env["HOME"]).mkdir()
        Path(user_env["TMPDIR"]).mkdir()
        _record_and_set(Path(user_env["HOME"]), uid=nobody.pw_uid, gid=nobody.pw_gid, mode=0o775)
        _record_and_set(Path(user_env["TMPDIR"]), uid=nobody.pw_uid, gid=nobody.pw_gid, mode=0o775)

        command = " && ".join(
            [
                f"cd {shlex.quote(str(workspace))}",
                "/bin/bash"
                f" {shlex.quote(str(collect_script))}"
                f" {shlex.quote(str(deploy))}"
                f" {shlex.quote(str(out_path))}",
            ]
        )

        failure = _run_as("nobody", command, cwd=workspace, env=user_env)
        assert failure.returncode != 0
        assert "Permission denied" in failure.stderr or "Operation not permitted" in failure.stderr

        fix_env = os.environ.copy()
        fix_env["TARGET_UID"] = str(nobody.pw_uid)
        fix_env["TARGET_GID"] = str(nobody.pw_gid)
        fix_result = subprocess.run(
            ["/bin/bash", str(fix_script)],
            cwd=workspace,
            env=fix_env,
            capture_output=True,
            text=True,
            check=True,
        )
        assert fix_result.returncode == 0

        success = _run_as("nobody", command, cwd=workspace, env=user_env)
        if success.returncode != 0:
            pytest.fail(
                "collect_pi_image.sh failed after permissions fix:\n"
                f"stdout:\n{success.stdout}\n"
                f"stderr:\n{success.stderr}"
            )

        assert success.returncode == 0
        assert out_path.stat().st_uid == nobody.pw_uid
        assert checksum_path.stat().st_uid == nobody.pw_uid
        assert deploy.stat().st_uid == nobody.pw_uid
    finally:
        for path, uid, gid, mode in reversed(original_permissions):
            os.chown(path, uid, gid)
            os.chmod(path, mode)
