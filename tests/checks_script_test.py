import os
import subprocess
from pathlib import Path


def test_skips_js_checks_when_package_lock_missing(tmp_path):
    script_src = Path(__file__).resolve().parents[1] / "scripts" / "checks.sh"
    script = tmp_path / "checks.sh"
    script.write_text(script_src.read_text())
    script.chmod(0o755)

    # simulate project with package.json but no package-lock.json
    (tmp_path / "package.json").write_text("{}")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "npm_called"
    for cmd in [
        "flake8",
        "isort",
        "black",
        "pytest",
        "pyspelling",
        "linkchecker",
        "npm",
        "npx",
    ]:
        f = fake_bin / cmd
        if cmd == "npm":
            f.write_text(f"#!/bin/bash\necho called > {marker}\nexit 0\n")
        else:
            f.write_text("#!/bin/bash\nexit 0\n")
        f.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"/bin:{fake_bin}"

    result = subprocess.run(
        ["/bin/bash", str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "package-lock.json not found" in result.stderr
    assert not marker.exists()


def test_skips_js_checks_when_npm_missing(tmp_path):
    script_src = Path(__file__).resolve().parents[1] / "scripts" / "checks.sh"
    script = tmp_path / "checks.sh"
    script.write_text(script_src.read_text())
    script.chmod(0o755)

    # simulate project with package.json but no npm installed
    (tmp_path / "package.json").write_text("{}")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "npx_called"
    for cmd in [
        "flake8",
        "isort",
        "black",
        "pytest",
        "pyspelling",
        "linkchecker",
        "npx",
    ]:
        f = fake_bin / cmd
        if cmd == "npx":
            f.write_text(f"#!/bin/bash\necho called > {marker}\nexit 0\n")
        else:
            f.write_text("#!/bin/bash\nexit 0\n")
        f.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"/bin:{fake_bin}"

    result = subprocess.run(
        ["/bin/bash", str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "npm not found" in result.stderr
    assert not marker.exists()
