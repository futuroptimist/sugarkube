import os
import shutil
import subprocess
from pathlib import Path


def test_requires_curl(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in [
        "docker",
        "git",
        "sha256sum",
        "stdbuf",
        "timeout",
        "xz",
        "unzip",
    ]:
        path = fake_bin / name
        if name == "timeout":
            path.write_text('#!/bin/sh\nshift\nexec "$@"\n')
        elif name == "stdbuf":
            path.write_text('#!/bin/sh\nshift\nshift\nexec "$@"\n')
        else:
            path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = str(fake_bin)
    result = subprocess.run(
        ["/bin/bash", "scripts/build_pi_image.sh"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "curl is required" in result.stderr


def test_requires_docker(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl = fake_bin / "curl"
    curl.write_text("#!/bin/sh\nexit 0\n")
    curl.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(fake_bin)
    result = subprocess.run(
        ["/bin/bash", "scripts/build_pi_image.sh"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "docker is required" in result.stderr


def test_requires_xz(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ["curl", "docker", "git", "sha256sum", "stdbuf", "timeout"]:
        path = fake_bin / name
        if name == "timeout":
            path.write_text('#!/bin/sh\nshift\nexec "$@"\n')
        elif name == "stdbuf":
            path.write_text('#!/bin/sh\nshift\nshift\nexec "$@"\n')
        else:
            path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(fake_bin)
    result = subprocess.run(
        ["/bin/bash", "scripts/build_pi_image.sh"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "xz is required" in result.stderr


def test_requires_unzip(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in [
        "curl",
        "docker",
        "git",
        "sha256sum",
        "stdbuf",
        "timeout",
        "xz",
    ]:
        path = fake_bin / name
        if name == "timeout":
            path.write_text('#!/bin/sh\nshift\nexec "$@"\n')
        elif name == "stdbuf":
            path.write_text('#!/bin/sh\nshift\nshift\nexec "$@"\n')
        else:
            path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(fake_bin)
    result = subprocess.run(
        ["/bin/bash", "scripts/build_pi_image.sh"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "unzip is required" in result.stderr


def test_requires_git(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name, content in {
        "curl": "#!/bin/sh\nexit 0\n",
        "docker": "#!/bin/sh\nexit 0\n",
        "xz": "#!/bin/sh\nexit 0\n",
    }.items():
        path = fake_bin / name
        path.write_text(content)
        path.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(fake_bin)
    result = subprocess.run(
        ["/bin/bash", "scripts/build_pi_image.sh"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "git is required" in result.stderr


def test_requires_sha256sum(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ["curl", "docker", "xz", "git"]:
        path = fake_bin / name
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(fake_bin)
    result = subprocess.run(
        ["/bin/bash", "scripts/build_pi_image.sh"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "sha256sum is required" in result.stderr


def test_docker_daemon_must_be_running(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text('#!/bin/sh\n[ "$1" = info ] && exit 1 || exit 0\n')
    docker.chmod(0o755)
    for name in ["xz", "git", "sha256sum", "unzip"]:
        path = fake_bin / name
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    for name in ["curl", "timeout", "stdbuf"]:
        path = fake_bin / name
        if name == "timeout":
            path.write_text('#!/bin/sh\nshift\nexec "$@"\n')
        elif name == "stdbuf":
            path.write_text('#!/bin/sh\nshift\nshift\nexec "$@"\n')
        else:
            path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(fake_bin)
    result = subprocess.run(
        ["/bin/bash", "scripts/build_pi_image.sh"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Docker daemon is not running or not accessible" in result.stderr


def test_requires_sudo_when_non_root(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name, content in {
        "docker": "#!/bin/sh\nexit 0\n",
        "xz": "#!/bin/sh\nexit 0\n",
        "git": "#!/bin/sh\nexit 0\n",
        "sha256sum": "#!/bin/sh\nexit 0\n",
        "id": "#!/bin/sh\necho 1000\n",
        "curl": "#!/bin/sh\nexit 0\n",
        "timeout": '#!/bin/sh\nshift\nexec "$@"\n',
        "stdbuf": "#!/bin/sh\nexit 0\n",
        "unzip": "#!/bin/sh\nexit 0\n",
    }.items():
        path = fake_bin / name
        path.write_text(content)
        path.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(fake_bin)
    result = subprocess.run(
        ["/bin/bash", "scripts/build_pi_image.sh"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Run as root or install sudo" in result.stderr


def _setup_build_env(
    tmp_path, check_compose: bool = False, precompressed: bool = False
):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    git_log = tmp_path / "git_args.log"

    (fake_bin / "docker").write_text("#!/bin/sh\nexit 0\n")
    (fake_bin / "docker").chmod(0o755)

    xz = fake_bin / "xz"
    xz.write_text('#!/bin/bash\n[ "$1" = "-T0" ] && shift\nmv "$1" "$1.xz"\n')
    xz.chmod(0o755)

    sha = fake_bin / "sha256sum"
    sha.write_text('#!/bin/sh\necho 0  "$1"\n')
    sha.chmod(0o755)

    compose_check = (
        "[[ -f stage2/01-sys-tweaks/files/opt/sugarkube/"
        "docker-compose.cloudflared.yml ]] || exit 1\n"
        if check_compose
        else ""
    )
    image_cmd = (
        "python3 - <<'PY'\n"
        "import zipfile\n"
        "with zipfile.ZipFile('deploy/sugarkube.img.zip', 'w') as zf:\n"
        "    zf.writestr('sugarkube.img', '')\n"
        "PY\n"
    )
    if precompressed:
        image_cmd = (
            "python3 - <<'PY'\n"
            "import lzma, pathlib\n"
            "pathlib.Path('deploy/sugarkube.img.xz').write_bytes("
            "lzma.compress(b''))\n"
            "PY\n"
        )
    git_stub = (
        f"#!/bin/bash\n"
        f'echo "$@" > "{git_log}"\n'
        "target=${!#}\n"
        'mkdir -p "$target/stage2/01-sys-tweaks"\n'
        f"cat <<'EOF' > \"$target/build.sh\"\n"
        "#!/bin/bash\n"
        f"{compose_check}"
        "mkdir -p deploy\n"
        f"{image_cmd}"
        "EOF\n"
        'chmod +x "$target/build.sh"\n'
    )
    git = fake_bin / "git"
    git.write_text(git_stub)
    git.chmod(0o755)

    for name in ["curl", "timeout", "stdbuf"]:
        path = fake_bin / name
        if name == "timeout":
            path.write_text(
                '#!/bin/sh\nfirst="$1"\nshift\n'
                'if [ -n "$TIMEOUT_LOG" ]; then\n'
                '  echo $first > "$TIMEOUT_LOG"\n'
                'fi\nexec "$@"\n'
            )
        elif name == "stdbuf":
            path.write_text('#!/bin/sh\nshift\nshift\nexec "$@"\n')
        else:
            path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)

    (fake_bin / "id").write_text("#!/bin/sh\necho 0\n")
    (fake_bin / "id").chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["GIT_LOG"] = str(git_log)
    return env


def _run_build_script(tmp_path, env):
    repo_root = Path(__file__).resolve().parents[1]
    script_src = repo_root / "scripts" / "build_pi_image.sh"
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    script = script_dir / "build_pi_image.sh"
    script.write_text(script_src.read_text())
    script.chmod(0o755)

    ci_dir = script_dir / "cloud-init"
    ci_dir.mkdir(parents=True)
    user_src = repo_root / "scripts" / "cloud-init" / "user-data.yaml"
    shutil.copy(user_src, ci_dir / "user-data.yaml")
    compose_src = (
        repo_root / "scripts" / "cloud-init" / "docker-compose.cloudflared.yml"
    )
    shutil.copy(compose_src, ci_dir / "docker-compose.cloudflared.yml")

    result = subprocess.run(
        ["/bin/bash", str(script)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    git_log_path = Path(env["GIT_LOG"])
    git_args = git_log_path.read_text() if git_log_path.exists() else ""
    return result, git_args


def test_uses_default_pi_gen_branch(tmp_path):
    env = _setup_build_env(tmp_path)
    env["ARM64"] = "0"
    result, git_args = _run_build_script(tmp_path, env)
    assert result.returncode == 0
    assert "--branch bookworm" in git_args
    assert (tmp_path / "sugarkube.img.xz").exists()


def test_arm64_build_uses_arm64_branch(tmp_path):
    env = _setup_build_env(tmp_path)
    result, git_args = _run_build_script(tmp_path, env)
    assert result.returncode == 0
    assert "--branch arm64" in git_args
    assert (tmp_path / "sugarkube.img.xz").exists()


def test_respects_pi_gen_branch_env(tmp_path):
    env = _setup_build_env(tmp_path)
    env["PI_GEN_BRANCH"] = "legacy"
    result, git_args = _run_build_script(tmp_path, env)
    assert result.returncode == 0
    assert "--branch legacy" in git_args
    assert (tmp_path / "sugarkube.img.xz").exists()


def test_handles_precompressed_pi_gen_output(tmp_path):
    env = _setup_build_env(tmp_path, precompressed=True)
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode == 0
    assert (tmp_path / "sugarkube.img.xz").exists()
    assert not (tmp_path / "sugarkube.img.xz.xz").exists()


def test_copies_cloudflared_compose(tmp_path):
    env = _setup_build_env(tmp_path, check_compose=True)
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode == 0


def test_build_without_timeout_binary(tmp_path):
    env = _setup_build_env(tmp_path)
    fake_bin = Path(env["PATH"].split(":")[0])
    (fake_bin / "timeout").unlink()
    # Remove system PATH so timeout is truly absent
    env["PATH"] = str(fake_bin)
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode != 0
    assert "timeout is required" in result.stderr


def test_build_without_stdbuf_binary(tmp_path):
    env = _setup_build_env(tmp_path)
    fake_bin = Path(env["PATH"].split(":")[0])
    (fake_bin / "stdbuf").unlink()
    env["PATH"] = str(fake_bin)
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode != 0
    assert "stdbuf is required" in result.stderr


def test_respects_build_timeout_env(tmp_path):
    env = _setup_build_env(tmp_path)
    env["BUILD_TIMEOUT"] = "2h"
    log = tmp_path / "timeout.log"
    env["TIMEOUT_LOG"] = str(log)
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode == 0
    assert log.read_text().strip() == "2h"


def test_requires_cloud_init_file(tmp_path):
    env = _setup_build_env(tmp_path)
    env["CLOUD_INIT_PATH"] = str(tmp_path / "missing.yaml")
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode != 0
    assert "Cloud-init file not found" in result.stderr


def test_powershell_script_mentions_cloudflared_compose():
    text = Path("scripts/build_pi_image.ps1").read_text()
    assert "docker-compose.cloudflared.yml" in text
