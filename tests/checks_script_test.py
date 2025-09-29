import os
import subprocess
import sys
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
    env["PATH"] = str(fake_bin)
    env["PYTHONPATH"] = str(tmp_path)

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
