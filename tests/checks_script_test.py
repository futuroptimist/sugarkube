from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def script(tmp_path: Path) -> Path:
    """Copy checks script and stub pcbnew to avoid KiCad install."""
    script_src = Path(__file__).resolve().parents[1] / "scripts" / "checks.sh"
    script = tmp_path / "checks.sh"
    script.write_text(script_src.read_text())
    script.chmod(0o755)
    installer_src = script_src.with_name("install_just.sh")
    installer = tmp_path / "install_just.sh"
    installer.write_text(installer_src.read_text())
    installer.chmod(0o755)
    # create dummy pcbnew module so checks.sh skips KiCad install
    (tmp_path / "pcbnew.py").write_text("")
    return script


def test_docs_only_mode_runs_docs_checks(tmp_path: Path, script: Path) -> None:
    (tmp_path / ".spellcheck.yaml").write_text("document: []\n")
    (tmp_path / "README.md").write_text("# README\n")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "index.md").write_text("# Docs\n")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    def make_stub(name: str, body: str) -> None:
        path = fake_bin / name
        path.write_text(body)
        path.chmod(0o755)

    skip_logs = {
        name: tmp_path / f"{name}.log"
        for name in [
            "flake8",
            "isort",
            "black",
            "pytest",
            "npm",
            "npx",
            "bats",
        ]
    }
    for name, log in skip_logs.items():
        make_stub(name, f"#!/bin/bash\necho run >> {log}\nexit 0\n")

    pyspelling_log = tmp_path / "pyspelling.log"
    make_stub(
        "pyspelling",
        f'#!/bin/bash\necho "$@" >> {pyspelling_log}\nexit 0\n',
    )

    linkchecker_log = tmp_path / "linkchecker.log"
    make_stub(
        "linkchecker",
        f'#!/bin/bash\necho "$@" >> {linkchecker_log}\nexit 0\n',
    )

    make_stub("aspell", "#!/bin/bash\nexit 0\n")

    pip_log = tmp_path / "pip.log"
    make_stub("pip", f"#!/bin/bash\necho pip >> {pip_log}\nexit 0\n")

    make_stub("python", f'#!/bin/bash\nexec {sys.executable} "$@"\n')

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["PYTHONPATH"] = str(tmp_path)

    result = subprocess.run(
        ["/bin/bash", str(script), "--docs-only"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert pyspelling_log.exists()
    assert any("--no-warnings" in line for line in linkchecker_log.read_text().splitlines())
    assert not pip_log.exists()
    for log in skip_logs.values():
        assert not log.exists()


def test_docs_only_mode_falls_back_to_python_module_pip(tmp_path: Path, script: Path) -> None:
    (tmp_path / ".spellcheck.yaml").write_text("document: []\n")
    (tmp_path / "README.md").write_text("# README\n")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "index.md").write_text("# Docs\n")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    python_log = tmp_path / "python-pip.log"
    pyspelling_log = tmp_path / "pyspelling.log"
    linkchecker_log = tmp_path / "linkchecker.log"

    def write_stub(path: Path, content: str) -> None:
        path.write_text(content)
        path.chmod(0o755)

    python_stub = f"""#!/bin/bash
if [ "$1" = "-m" ] && [ "$2" = "pip" ] && [ "$3" = "install" ]; then
  echo "$@" >> "{python_log}"
  if [ -x /bin/cat ]; then CAT=/bin/cat; else CAT=/usr/bin/cat; fi
  if [ -x /bin/chmod ]; then CHMOD=/bin/chmod; else CHMOD=/usr/bin/chmod; fi
  "$CAT" > "{fake_bin / 'pyspelling'}" <<'PY'
#!/bin/bash
echo "$@" >> "{pyspelling_log}"
exit 0
PY
  "$CHMOD" +x "{fake_bin / 'pyspelling'}"
  "$CAT" > "{fake_bin / 'linkchecker'}" <<'LC'
#!/bin/bash
echo "$@" >> "{linkchecker_log}"
exit 0
LC
  "$CHMOD" +x "{fake_bin / 'linkchecker'}"
  exit 0
fi
echo "unexpected args: $@" >&2
exit 1
"""

    write_stub(fake_bin / "python", python_stub)
    write_stub(
        fake_bin / "python3",
        f"#!/bin/bash\nexec \"{fake_bin / 'python'}\" \"$@\"\n",
    )
    write_stub(fake_bin / "aspell", "#!/bin/bash\nexit 0\n")
    write_stub(
        fake_bin / "id",
        textwrap.dedent(
            """\
            #!/bin/bash
            if [ "$1" = "-u" ]; then
              echo 1000
            else
              exit 0
            fi
            """
        ),
    )

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"
    env["PYTHONPATH"] = str(tmp_path)
    env["SUGARKUBE_DOCS_FORCE_INSTALL"] = "1"
    env["SUGARKUBE_DOCS_FORCE_PYTHON_PIP"] = "1"

    result = subprocess.run(
        ["/bin/bash", str(script), "--docs-only"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert python_log.exists(), "expected python -m pip fallback to run"
    log_line = python_log.read_text().strip()
    assert "-m pip install pyspelling linkchecker" in log_line
    assert pyspelling_log.exists(), "pyspelling command should run after installation"
    assert linkchecker_log.exists(), "linkchecker command should run after installation"


def test_docs_only_skip_install_uses_existing_tools(tmp_path: Path, script: Path) -> None:
    """`--skip-install` should skip bootstrapping dependencies in docs-only mode."""

    (tmp_path / ".spellcheck.yaml").write_text("document: []\n")
    (tmp_path / "README.md").write_text("# README\n")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "index.md").write_text("# Docs\n")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    def write_stub(name: str, body: str) -> Path:
        path = fake_bin / name
        path.write_text(body)
        path.chmod(0o755)
        return path

    pip_log = tmp_path / "pip.log"
    write_stub("pip", f"#!/bin/bash\necho pip >> {pip_log}\nexit 1\n")

    apt_log = tmp_path / "apt.log"
    write_stub("apt-get", f"#!/bin/bash\necho apt >> {apt_log}\nexit 1\n")
    write_stub("sudo", f"#!/bin/bash\necho sudo >> {apt_log}\nexit 1\n")

    write_stub("id", '#!/bin/bash\nif [ "$1" = "-u" ]; then echo 1000; else exit 0; fi\n')

    write_stub(
        "pyspelling",
        "#!/bin/bash\nexit 0\n",
    )
    write_stub(
        "linkchecker",
        "#!/bin/bash\nexit 0\n",
    )
    write_stub("aspell", "#!/bin/bash\nexit 0\n")
    write_stub("python", f'#!/bin/bash\nexec {sys.executable} "$@"\n')

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["PYTHONPATH"] = str(tmp_path)

    result = subprocess.run(
        ["/bin/bash", str(script), "--docs-only", "--skip-install"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert not pip_log.exists(), "pip should not run when --skip-install is set"
    assert not apt_log.exists(), "apt-get/sudo should not run when --skip-install is set"


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


def test_skip_install_avoids_dependency_bootstrap(tmp_path: Path, script: Path) -> None:
    """Full runs should respect --skip-install and rely on existing tooling."""

    (tmp_path / ".spellcheck.yaml").write_text("document: []\n")
    (tmp_path / "README.md").write_text("# README\n")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "index.md").write_text("# Docs\n")

    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "package-lock.json").write_text("{}")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    def write_stub(name: str, body: str) -> Path:
        path = fake_bin / name
        path.write_text(body)
        path.chmod(0o755)
        return path

    pip_log = tmp_path / "pip.log"
    write_stub("pip", f"#!/bin/bash\necho pip >> {pip_log}\nexit 1\n")

    apt_log = tmp_path / "apt.log"
    write_stub("apt-get", f"#!/bin/bash\necho apt >> {apt_log}\nexit 1\n")
    write_stub("sudo", f"#!/bin/bash\necho sudo >> {apt_log}\nexit 1\n")
    write_stub("brew", f"#!/bin/bash\necho brew >> {apt_log}\nexit 1\n")

    write_stub("id", '#!/bin/bash\nif [ "$1" = "-u" ]; then echo 1000; else exit 0; fi\n')

    for command in [
        "flake8",
        "isort",
        "black",
        "pytest",
        "coverage",
        "pyspelling",
        "linkchecker",
        "npm",
        "npx",
        "bats",
        "aspell",
    ]:
        if command in {"npm", "npx"}:
            body = "#!/bin/bash\nexit 0\n"
        else:
            body = "#!/bin/bash\nexit 0\n"
        write_stub(command, body)

    write_stub("python", f'#!/bin/bash\nexec {sys.executable} "$@"\n')

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["PYTHONPATH"] = str(tmp_path)

    result = subprocess.run(
        ["/bin/bash", str(script), "--skip-install"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert not pip_log.exists(), "pip should not run when --skip-install is set"
    assert not apt_log.exists(), "System package managers should not run when --skip-install is set"


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
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"

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
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"

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


def test_installs_kicad_when_kicad_assets_change(tmp_path: Path, script: Path) -> None:
    # Remove the stub pcbnew module so the script attempts installation.
    pcbnew_stub = tmp_path / "pcbnew.py"
    pcbnew_stub.unlink()

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "board.kicad_pcb").write_text("")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    apt_log = tmp_path / "apt.log"
    repo_log = tmp_path / "add-repo.log"

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
        "pip",
    ]:
        f = fake_bin / cmd
        f.write_text("#!/bin/bash\nexit 0\n")
        f.chmod(0o755)

    python_cmd = fake_bin / "python"
    python_cmd.write_text(f'#!/bin/bash\nexec {sys.executable} "$@"\n')
    python_cmd.chmod(0o755)

    apt_get = fake_bin / "apt-get"
    apt_get.write_text(
        f"""#!/bin/bash
echo "$@" >> {apt_log}
if [[ " $* " == *" install "* && " $* " == *" kicad"* ]]; then
  cat <<'PY' > {tmp_path}/pcbnew.py
# stub KiCad pcbnew module
PY
fi
exit 0
"""
    )
    apt_get.chmod(0o755)

    add_repo = fake_bin / "add-apt-repository"
    add_repo.write_text(
        f"""#!/bin/bash
echo "$@" >> {repo_log}
exit 0
"""
    )
    add_repo.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["PYTHONPATH"] = str(tmp_path)

    result = subprocess.run(
        ["/bin/bash", str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "install -y kicad" in apt_log.read_text()
    assert pcbnew_stub.exists()


def test_uses_system_python_when_pyenv_lacks_pcbnew(tmp_path: Path, script: Path) -> None:
    pcbnew_stub = tmp_path / "pcbnew.py"
    pcbnew_stub.unlink()

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "board.kicad_pcb").write_text("")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    apt_log = tmp_path / "apt.log"
    repo_log = tmp_path / "add-repo.log"
    python3_log = tmp_path / "python3.log"

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
        "pip",
    ]:
        f = fake_bin / cmd
        f.write_text("#!/bin/bash\nexit 0\n")
        f.chmod(0o755)

    python_cmd = fake_bin / "python"
    python_cmd.write_text(f'#!/bin/bash\ncd /\nexec {sys.executable} "$@"\n')
    python_cmd.chmod(0o755)

    python3_cmd = fake_bin / "python3"
    python3_cmd.write_text(
        f"""#!/bin/bash
echo "$@" >> {python3_log}
PYTHONPATH="{tmp_path}:${{PYTHONPATH:-}}" exec {sys.executable} "$@"
"""
    )
    python3_cmd.chmod(0o755)

    apt_get = fake_bin / "apt-get"
    apt_get.write_text(
        f"""#!/bin/bash
echo "$@" >> {apt_log}
if [[ " $* " == *" install "* && " $* " == *" kicad"* ]]; then
  cat <<'PY' > {tmp_path}/pcbnew.py
# stub KiCad pcbnew module
PY
fi
exit 0
"""
    )
    apt_get.chmod(0o755)

    add_repo = fake_bin / "add-apt-repository"
    add_repo.write_text(
        f"""#!/bin/bash
echo "$@" >> {repo_log}
exit 0
"""
    )
    add_repo.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["PYTHONPATH"] = str(tmp_path)

    result = subprocess.run(
        ["/bin/bash", str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "install -y kicad" in apt_log.read_text()
    assert python3_log.read_text().strip() != ""
    assert pcbnew_stub.exists()


def test_installs_kicad_in_shallow_checkout(tmp_path: Path, script: Path) -> None:
    pcbnew_stub = tmp_path / "pcbnew.py"
    pcbnew_stub.unlink()

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "ci@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "CI Runner"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    board = tmp_path / "board.kicad_pcb"
    board.write_text("")
    subprocess.run(
        ["git", "add", board.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add board"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    apt_log = tmp_path / "apt.log"
    repo_log = tmp_path / "add-repo.log"

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
        "pip",
    ]:
        f = fake_bin / cmd
        f.write_text("#!/bin/bash\nexit 0\n")
        f.chmod(0o755)

    python_cmd = fake_bin / "python"
    python_cmd.write_text(f'#!/bin/bash\nexec {sys.executable} "$@"\n')
    python_cmd.chmod(0o755)

    apt_get = fake_bin / "apt-get"
    apt_get.write_text(
        f"""#!/bin/bash
echo "$@" >> {apt_log}
if [[ " $* " == *" install "* && " $* " == *" kicad"* ]]; then
  cat <<'PY' > {tmp_path}/pcbnew.py
# stub KiCad pcbnew module
PY
fi
exit 0
"""
    )
    apt_get.chmod(0o755)

    add_repo = fake_bin / "add-apt-repository"
    add_repo.write_text(
        f"""#!/bin/bash
echo "$@" >> {repo_log}
exit 0
"""
    )
    add_repo.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["PYTHONPATH"] = str(tmp_path)
    env["CI"] = "1"
    env["GITHUB_BASE_REF"] = "main"
    env["GITHUB_SHA"] = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    result = subprocess.run(
        ["/bin/bash", str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "install -y kicad" in apt_log.read_text()
    assert pcbnew_stub.exists()


def test_installs_kicad_when_history_is_shallow(tmp_path: Path) -> None:
    script_src = Path(__file__).resolve().parents[1] / "scripts" / "checks.sh"

    script_path = tmp_path / "checks.sh"
    script_path.write_text(script_src.read_text())
    script_path.chmod(0o755)

    source_repo = tmp_path / "source"
    source_repo.mkdir()
    subprocess.run(["git", "init"], cwd=source_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "ci@example.com"],
        cwd=source_repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "CI Runner"],
        cwd=source_repo,
        check=True,
        capture_output=True,
    )

    (source_repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "README.md"], cwd=source_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial base"],
        cwd=source_repo,
        check=True,
        capture_output=True,
    )

    remote_repo = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote_repo)],
        check=True,
        capture_output=True,
    )

    subprocess.run(
        ["git", "branch", "-M", "main"],
        cwd=source_repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote_repo)],
        cwd=source_repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=source_repo,
        check=True,
        capture_output=True,
    )

    subprocess.run(
        ["git", "checkout", "-b", "feature"],
        cwd=source_repo,
        check=True,
        capture_output=True,
    )

    (source_repo / "board.kicad_pcb").write_text("")
    subprocess.run(
        ["git", "add", "board.kicad_pcb"],
        cwd=source_repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Add KiCad board"],
        cwd=source_repo,
        check=True,
        capture_output=True,
    )

    (source_repo / "README.md").write_text("base\nupdate\n")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=source_repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Docs tweak"],
        cwd=source_repo,
        check=True,
        capture_output=True,
    )

    subprocess.run(
        ["git", "push", "-u", "origin", "feature"],
        cwd=source_repo,
        check=True,
        capture_output=True,
    )

    shallow_repo = tmp_path / "shallow"
    subprocess.run(
        [
            "git",
            "clone",
            "--depth=1",
            "--branch",
            "feature",
            str(remote_repo),
            str(shallow_repo),
        ],
        check=True,
        capture_output=True,
    )

    clone_script = shallow_repo / "checks.sh"
    clone_script.write_text(script_path.read_text())
    clone_script.chmod(0o755)

    pcbnew_stub = shallow_repo / "pcbnew.py"
    if pcbnew_stub.exists():
        pcbnew_stub.unlink()

    fake_bin = shallow_repo / "bin"
    fake_bin.mkdir()
    apt_log = shallow_repo / "apt.log"
    repo_log = shallow_repo / "add-repo.log"

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
        "pip",
        "uv",
    ]:
        f = fake_bin / cmd
        f.write_text("#!/bin/bash\nexit 0\n")
        f.chmod(0o755)

    python_cmd = fake_bin / "python"
    python_cmd.write_text(f'#!/bin/bash\nexec {sys.executable} "$@"\n')
    python_cmd.chmod(0o755)

    apt_get = fake_bin / "apt-get"
    apt_get.write_text(
        f"""#!/bin/bash
echo "$@" >> {apt_log}
if [[ " $* " == *" install "* && " $* " == *" kicad"* ]]; then
  cat <<'PY' > {pcbnew_stub}
# stub KiCad pcbnew module
PY
fi
exit 0
"""
    )
    apt_get.chmod(0o755)

    add_repo = fake_bin / "add-apt-repository"
    add_repo.write_text(
        f"""#!/bin/bash
echo "$@" >> {repo_log}
exit 0
"""
    )
    add_repo.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["PYTHONPATH"] = str(shallow_repo)
    env["CI"] = "1"
    env["GITHUB_BASE_REF"] = "main"
    env["GITHUB_SHA"] = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=shallow_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    result = subprocess.run(
        ["/bin/bash", str(clone_script)],
        cwd=shallow_repo,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "install -y kicad" in apt_log.read_text()
    assert pcbnew_stub.exists()


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


def test_bootstraps_just_when_missing(tmp_path: Path, script: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    _prepare_command_stubs(fake_bin)

    tar_path = shutil.which("tar")
    chmod_path = shutil.which("chmod")
    dirname_path = shutil.which("dirname")
    assert tar_path and chmod_path, "tar and chmod must be available for bootstrap stubs"

    for name, target in (("tar", tar_path), ("chmod", chmod_path)):
        stub = fake_bin / name
        stub.write_text(f"#!/bin/bash\nexec {target} \"$@\"\n")
        stub.chmod(0o755)

    if dirname_path:
        stub = fake_bin / "dirname"
        stub.write_text(f"#!/bin/bash\nexec {dirname_path} \"$@\"\n")
        stub.chmod(0o755)

    just_stub = tmp_path / "just"
    just_stub.write_text("#!/usr/bin/env bash\necho bootstrap\n", encoding="utf-8")
    just_stub.chmod(0o755)

    tarball = tmp_path / "just.tar.gz"
    with tarfile.open(tarball, "w:gz") as archive:
        archive.add(just_stub, arcname="just")

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"
    env["PYTHONPATH"] = str(tmp_path)
    env["SUGARKUBE_JUST_TARBALL"] = str(tarball)
    env["SUGARKUBE_JUST_BIN_DIR"] = str(tmp_path / "just-bin")
    env["SUGARKUBE_JUST_FORCE_INSTALL"] = "1"

    result = subprocess.run(
        ["/bin/bash", str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    installed = Path(env["SUGARKUBE_JUST_BIN_DIR"]) / "just"
    assert installed.exists(), "checks.sh should install just when missing"
    assert installed.stat().st_mode & 0o111


def _prepare_command_stubs(fake_bin: Path, env_log: Path | None = None) -> None:
    def write_stub(name: str, body: str) -> None:
        path = fake_bin / name
        path.write_text(body)
        path.chmod(0o755)

    for name in ("flake8", "isort", "black", "pyspelling", "linkchecker", "coverage", "npm", "npx"):
        write_stub(name, "#!/bin/bash\nexit 0\n")

    pytest_body = "#!/bin/bash\n"
    if env_log is not None:
        pytest_body += f"env | sort > \"{env_log}\"\n"
    pytest_body += "exit 5\n"
    write_stub("pytest", pytest_body)
    write_stub("bats", "#!/bin/bash\nexit 0\n")

    write_stub(
        "id",
        "#!/bin/bash\n"
        "if [ \"$1\" = \"-u\" ]; then\n"
        "  echo 1000\n"
        "else\n"
        "  exec /usr/bin/id \"$@\"\n"
        "fi\n",
    )


def test_exports_test_env_defaults(tmp_path: Path, script: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    env_log = tmp_path / "pytest-env.log"

    _prepare_command_stubs(fake_bin, env_log)

    (tmp_path / "tests" / "bats").mkdir(parents=True)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["PYTHONPATH"] = str(tmp_path)
    env.pop("ALLOW_NON_ROOT", None)
    env.pop("BATS_CWD", None)
    env.pop("BATS_LIB_PATH", None)
    env["SKIP_INSTALL"] = "1"

    result = subprocess.run(
        ["/bin/bash", str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert env_log.exists(), "pytest stub should capture environment variables"

    logged_env = {
        line.split("=", maxsplit=1)[0]: line.split("=", maxsplit=1)[1]
        for line in env_log.read_text().splitlines()
        if "=" in line
    }

    assert logged_env.get("ALLOW_NON_ROOT") == "1"
    assert logged_env.get("BATS_CWD") == str(tmp_path)
    assert logged_env.get("BATS_LIB_PATH") == str(tmp_path / "tests" / "bats")


def test_rejects_conflicting_allow_non_root(tmp_path: Path, script: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    _prepare_command_stubs(fake_bin)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["PYTHONPATH"] = str(tmp_path)
    env["ALLOW_NON_ROOT"] = "0"
    env["SKIP_INSTALL"] = "1"

    result = subprocess.run(
        ["/bin/bash", str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "ALLOW_NON_ROOT" in result.stderr
