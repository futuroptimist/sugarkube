import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def script(tmp_path: Path) -> Path:
    """Copy checks script and stub pcbnew to avoid KiCad install."""
    script_src = Path(__file__).resolve().parents[1] / "scripts" / "checks.sh"
    script = tmp_path / "checks.sh"
    script.write_text(script_src.read_text())
    script.chmod(0o755)
    # create dummy pcbnew module so checks.sh skips KiCad install
    (tmp_path / "pcbnew.py").write_text("")
    return script


def test_skips_js_checks_when_package_lock_missing(tmp_path: Path, script: Path) -> None:
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
        "aspell",
        "npm",
        "npx",
        "python",
    ]:
        f = fake_bin / cmd
        if cmd == "npm":
            f.write_text(f"#!/bin/bash\necho called > {marker}\nexit 0\n")
        elif cmd == "python":
            f.write_text(f'#!/bin/bash\nexec {sys.executable} "$@"\n')
        else:
            f.write_text("#!/bin/bash\nexit 0\n")
        f.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:/bin"

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


def test_runs_js_checks_when_package_lock_present(tmp_path: Path, script: Path) -> None:
    # project with package.json and package-lock.json
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "package-lock.json").write_text("{}")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    npm_log = tmp_path / "npm.log"
    npx_log = tmp_path / "npx.log"
    for cmd in [
        "flake8",
        "isort",
        "black",
        "pytest",
        "pyspelling",
        "linkchecker",
        "aspell",
        "npm",
        "npx",
        "python",
    ]:
        f = fake_bin / cmd
        if cmd == "npm":
            f.write_text(f'#!/bin/bash\necho "$@" >> {npm_log}\nexit 0\n')
        elif cmd == "npx":
            f.write_text(f'#!/bin/bash\necho "$@" >> {npx_log}\nexit 0\n')
        elif cmd == "python":
            f.write_text(f'#!/bin/bash\nexec {sys.executable} "$@"\n')
        else:
            f.write_text("#!/bin/bash\nexit 0\n")
        f.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:/bin"

    result = subprocess.run(
        ["/bin/bash", str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    npm_lines = npm_log.read_text().splitlines()
    assert "ci" in npm_lines
    assert any("run lint" in line for line in npm_lines)
    assert any("run format:check" in line for line in npm_lines)
    assert any("test -- --coverage" in line for line in npm_lines)
    npx_lines = npx_log.read_text().splitlines()
    assert any("playwright install --with-deps" in line for line in npx_lines)


def test_installs_aspell_as_root_without_sudo(tmp_path: Path, script: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    apt_log = tmp_path / "apt.log"
    for cmd in [
        "flake8",
        "isort",
        "black",
        "pytest",
        "pyspelling",
        "linkchecker",
        "apt-get",
        "id",
        "python",
    ]:
        f = fake_bin / cmd
        if cmd == "apt-get":
            f.write_text(f'#!/bin/bash\necho "$@" >> {apt_log}\nexit 0\n')
        elif cmd == "id":
            f.write_text("#!/bin/bash\necho 0\n")
        elif cmd == "python":
            f.write_text(f'#!/bin/bash\nexec {sys.executable} "$@"\n')
        else:
            f.write_text("#!/bin/bash\nexit 0\n")
        f.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = str(fake_bin)

    result = subprocess.run(
        ["/bin/bash", str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    log = apt_log.read_text().splitlines()
    assert any("update" in line for line in log)
    assert any("install" in line for line in log)


def test_installs_aspell_with_sudo_when_non_root(tmp_path: Path, script: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sudo_log = tmp_path / "sudo.log"
    for cmd in [
        "flake8",
        "isort",
        "black",
        "pytest",
        "pyspelling",
        "linkchecker",
        "apt-get",
        "sudo",
        "id",
        "python",
    ]:
        f = fake_bin / cmd
        if cmd == "sudo":
            f.write_text(
                f"""#!/bin/bash
echo "$@" >> {sudo_log}
"$@"
"""
            )
        elif cmd == "id":
            f.write_text("#!/bin/bash\necho 1000\n")
        elif cmd == "python":
            f.write_text(f'#!/bin/bash\nexec {sys.executable} "$@"\n')
        else:
            f.write_text("#!/bin/bash\nexit 0\n")
        f.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = str(fake_bin)

    result = subprocess.run(
        ["/bin/bash", str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    lines = sudo_log.read_text().splitlines()
    assert any("apt-get update" in line for line in lines)
    assert any("apt-get install" in line for line in lines)


def test_skips_js_checks_when_npm_missing(tmp_path: Path, script: Path) -> None:
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
        "aspell",
        "npx",
        "python",
    ]:
        f = fake_bin / cmd
        if cmd == "npx":
            f.write_text(f"#!/bin/bash\necho called > {marker}\nexit 0\n")
        elif cmd == "python":
            f.write_text(f'#!/bin/bash\nexec {sys.executable} "$@"\n')
        else:
            f.write_text("#!/bin/bash\nexit 0\n")
        f.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:/bin"

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


def test_fails_when_flake8_fails(tmp_path: Path, script: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "flake8").write_text("#!/bin/bash\nexit 1\n")
    for cmd in ["isort", "black", "pytest", "pyspelling", "linkchecker", "python"]:
        f = fake_bin / cmd
        if cmd == "python":
            f.write_text(f'#!/bin/bash\nexec {sys.executable} "$@"\n')
        else:
            f.write_text("#!/bin/bash\nexit 0\n")
        f.chmod(0o755)
    (fake_bin / "flake8").chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:/bin"

    result = subprocess.run(
        ["/bin/bash", str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1


def test_installs_python_tools_when_missing(tmp_path: Path, script: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    pip_log = tmp_path / "pip.log"

    pip = fake_bin / "pip"
    pip.write_text(
        f"""#!/bin/bash
echo "$@" >> {pip_log}
for tool in flake8 isort black pytest pyspelling linkchecker; do
  cat <<'EOF' > {fake_bin}/$tool
#!/bin/bash
exit 0
EOF
  chmod +x {fake_bin}/$tool
done
exit 0
"""
    )
    pip.chmod(0o755)

    for cmd in ["aspell", "bats", "python"]:
        f = fake_bin / cmd
        if cmd == "python":
            f.write_text(f'#!/bin/bash\nexec {sys.executable} "$@"\n')
        else:
            f.write_text("#!/bin/bash\nexit 0\n")
        f.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:/bin"

    result = subprocess.run(
        ["/bin/bash", str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "flake8" in pip_log.read_text()
