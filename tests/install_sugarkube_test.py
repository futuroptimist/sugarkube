import os
import subprocess
from pathlib import Path

SCRIPT = Path("scripts/install_sugarkube.sh")


def make_stub(directory: Path, name: str, content: str = "#!/bin/sh\nexit 0\n") -> None:
    path = directory / name
    path.write_text(content)
    path.chmod(0o755)


def run_script(args, env):
    return subprocess.run(
        ["/bin/bash", str(SCRIPT), *args],
        env=env,
        text=True,
        capture_output=True,
    )


def test_install_script_requires_curl(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ["xz", "dd", "gh", "sha256sum"]:
        make_stub(fake_bin, name)
    env = os.environ.copy()
    env["PATH"] = str(fake_bin)
    env["SUGARKUBE_INSTALLER_ASSUME_GH"] = "1"
    result = run_script(["--dry-run"], env)
    assert result.returncode != 0
    assert "Missing required command: curl" in result.stderr


def test_install_script_dry_run(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ["curl", "xz", "dd", "gh", "sha256sum"]:
        make_stub(fake_bin, name)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{os.environ['PATH']}"
    env["SUGARKUBE_INSTALLER_ASSUME_GH"] = "1"
    result = run_script(["--dry-run", "--output", str(tmp_path / "sugarkube.img")], env)
    assert result.returncode == 0
    assert "Dry run" in result.stdout
