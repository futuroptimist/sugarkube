import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


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
        "bsdtar",
        "df",
        "python3",
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
    for name in [
        "curl",
        "git",
        "sha256sum",
        "stdbuf",
        "timeout",
        "xz",
        "bsdtar",
        "df",
        "python3",
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
    assert "docker is required" in result.stderr


def test_requires_xz(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in [
        "curl",
        "docker",
        "git",
        "sha256sum",
        "stdbuf",
        "timeout",
        "bsdtar",
        "df",
        "python3",
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
    assert "xz is required" in result.stderr


def test_requires_bsdtar(tmp_path):
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
        "df",
        "python3",
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
    assert "bsdtar is required" in result.stderr


def test_requires_df(tmp_path):
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
        "bsdtar",
        "python3",
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
    assert "df is required" in result.stderr


def test_requires_git(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name, content in {
        "curl": "#!/bin/sh\nexit 0\n",
        "docker": "#!/bin/sh\nexit 0\n",
        "sha256sum": "#!/bin/sh\nexit 0\n",
        "stdbuf": '#!/bin/sh\nshift\nshift\nexec "$@"\n',
        "timeout": '#!/bin/sh\nshift\nexec "$@"\n',
        "xz": "#!/bin/sh\nexit 0\n",
        "bsdtar": "#!/bin/sh\nexit 0\n",
        "df": "#!/bin/sh\nexit 0\n",
        "python3": "#!/bin/sh\nexit 0\n",
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
    for name in [
        "curl",
        "docker",
        "git",
        "stdbuf",
        "timeout",
        "xz",
        "bsdtar",
        "df",
        "python3",
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
    assert "sha256sum is required" in result.stderr


def test_docker_daemon_must_be_running(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text('#!/bin/sh\n[ "$1" = info ] && exit 1 || exit 0\n')
    docker.chmod(0o755)
    for name in ["xz", "git", "sha256sum", "bsdtar", "df", "python3"]:
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
        "bsdtar": "#!/bin/sh\nexit 0\n",
        "df": "#!/bin/sh\nexit 0\n",
        "python3": "#!/bin/sh\nexit 0\n",
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


def test_fails_with_insufficient_disk_space(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name, content in {
        "curl": "#!/bin/sh\nexit 0\n",
        "docker": "#!/bin/sh\nexit 0\n",
        "git": "#!/bin/sh\nexit 0\n",
        "sha256sum": "#!/bin/sh\nexit 0\n",
        "stdbuf": '#!/bin/sh\nshift\nshift\nexec "$@"\n',
        "timeout": '#!/bin/sh\nshift\nexec "$@"\n',
        "xz": "#!/bin/sh\nexit 0\n",
        "bsdtar": "#!/bin/sh\nexit 0\n",
        "df": (
            "#!/bin/sh\n"
            "echo 'Filesystem 1024-blocks Used Available Capacity Mounted on'\n"
            "echo '/dev/sda1 100 50 0 50% /'\n"
        ),
        "python3": "#!/bin/sh\nexit 0\n",
    }.items():
        path = fake_bin / name
        path.write_text(content)
        path.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["SKIP_BINFMT"] = "1"
    env["SKIP_URL_CHECK"] = "1"
    result = subprocess.run(
        ["/bin/bash", "scripts/build_pi_image.sh"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Need at least" in result.stderr


def _setup_build_env(
    tmp_path,
    precompressed: bool = False,
    nested_log: bool = False,
    compressed_log: bool = False,
    gzip_log: bool = False,
    stage_log: bool = False,
):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    git_log = tmp_path / "git_args.log"

    (fake_bin / "docker").write_text("#!/bin/sh\nexit 0\n")
    (fake_bin / "docker").chmod(0o755)

    xz = fake_bin / "xz"
    xz.write_text(
        """#!/bin/sh
set -e
while [ "${1#-}" != "$1" ]; do shift; done
case "$1" in
  *.xz)
    python3 - "$1" <<'PY'
import lzma, pathlib, sys
path = pathlib.Path(sys.argv[1])
sys.stdout.buffer.write(lzma.decompress(path.read_bytes()))
PY
    ;;
  *)
    cat "$1"
    ;;
esac
"""
    )
    xz.chmod(0o755)
    gzip_bin = fake_bin / "gzip"
    gzip_bin.write_text(
        """#!/bin/sh
set -e
if [ "$1" = "-dc" ]; then
  shift
  python3 - "$1" <<'PY'
import gzip, pathlib, sys
path = pathlib.Path(sys.argv[1])
sys.stdout.buffer.write(gzip.decompress(path.read_bytes()))
PY
  exit 0
fi
exec /bin/gzip "$@"
"""
    )
    gzip_bin.chmod(0o755)
    sha = fake_bin / "sha256sum"
    sha.write_text('#!/bin/sh\necho 0  "$1"\n')
    sha.chmod(0o755)

    bsdtar = fake_bin / "bsdtar"
    bsdtar.write_text(
        """#!/bin/sh
if [ "$1" = "-xf" ]; then
  zipfile=$2; shift 2
  if [ "$1" = "-C" ]; then
    dir=$2
    python3 - "$zipfile" "$dir" <<'PY'
import sys, zipfile
zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])
PY
  fi
fi
"""
    )
    bsdtar.chmod(0o755)
    df = fake_bin / "df"
    df.write_text("#!/bin/sh\nexit 0\n")
    df.chmod(0o755)
    mount = fake_bin / "mount"
    mount.write_text("#!/bin/sh\nexit 0\n")
    mount.chmod(0o755)

    image_cmd = (
        "python3 - <<'PY'\n"
        "import zipfile\n"
        "with zipfile.ZipFile('deploy/sugarkube.img.zip', 'w') as zf:\n"
        "    zf.writestr('sugarkube.img', 'pi')\n"
        "PY\n"
    )
    if precompressed:
        image_cmd = (
            "python3 - <<'PY'\n"
            "import lzma, pathlib\n"
            "pathlib.Path('deploy/sugarkube.img.xz').write_bytes("
            "lzma.compress(b'pi'))\n"
            "PY\n"
        )
    git_stub = (
        f"#!/bin/bash\n"
        f'echo "$@" >> "{git_log}"\n'
        "target=${!#}\n"
        'mkdir -p "$target/stage2/01-sys-tweaks"\n'
        f"cat <<'EOF' > \"$target/build.sh\"\n"
        "#!/bin/bash\n"
        "mkdir -p deploy\n"
        'cp config "$OUTPUT_DIR/config.env"\n'
        f"{image_cmd}"
        'if [ "${PI_GEN_STAGE_JUST_LOG:-0}" -eq 1 ]; then\n'
        "  mkdir -p work/sugarkube/logs/stage2/01-sys-tweaks\n"
        "  printf '[sugarkube] just command verified\\n[sugarkube] just version: stub\\n' > "
        "work/sugarkube/logs/stage2/01-sys-tweaks/03-run-chroot.log\n"
        "  mkdir -p work/sugarkube\n"
        "  printf '[sugarkube] stage logs archived\\n' > work/sugarkube/build.log\n"
        "  build_log_path=work/sugarkube/build.log\n"
        'elif [ "${PI_GEN_NESTED_BUILD_LOG:-0}" -eq 1 ]; then\n'
        "  mkdir -p work/sugarkube/logs/2025-10-31\n"
        "  printf '[sugarkube] just command verified\\n[sugarkube] just version: stub\\n' > "
        "work/sugarkube/logs/2025-10-31/build.log\n"
        "  build_log_path=work/sugarkube/logs/2025-10-31/build.log\n"
        "else\n"
        "  mkdir -p work/sugarkube\n"
        "  printf '[sugarkube] just command verified\\n[sugarkube] just version: stub\\n' > "
        "work/sugarkube/build.log\n"
        "  build_log_path=work/sugarkube/build.log\n"
        "fi\n"
        'if [ "${PI_GEN_COMPRESSED_BUILD_LOG:-0}" -eq 1 ]; then\n'
        "  BUILD_LOG_PATH=\"$build_log_path\" python3 - <<'PY'\n"
        "import lzma, os, pathlib\n"
        "path = pathlib.Path(os.environ['BUILD_LOG_PATH'])\n"
        "data = path.read_bytes()\n"
        "path.unlink()\n"
        "path.with_suffix(path.suffix + '.xz').write_bytes(lzma.compress(data))\n"
        "PY\n"
        "fi\n"
        'if [ "${PI_GEN_GZIP_BUILD_LOG:-0}" -eq 1 ]; then\n'
        "  BUILD_LOG_PATH=\"$build_log_path\" python3 - <<'PY'\n"
        "import gzip, os, pathlib\n"
        "path = pathlib.Path(os.environ['BUILD_LOG_PATH'])\n"
        "data = path.read_bytes()\n"
        "path.unlink()\n"
        "with gzip.open(path.with_suffix(path.suffix + '.gz'), 'wb') as fh:\n"
        "    fh.write(data)\n"
        "PY\n"
        "fi\n"
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
    if nested_log:
        env["PI_GEN_NESTED_BUILD_LOG"] = "1"
    if compressed_log:
        env["PI_GEN_COMPRESSED_BUILD_LOG"] = "1"
    if gzip_log:
        env["PI_GEN_GZIP_BUILD_LOG"] = "1"
    if stage_log:
        env["PI_GEN_STAGE_JUST_LOG"] = "1"
    return env


def _run_build_script(tmp_path, env):
    repo_root = Path(__file__).resolve().parents[1]
    script_src = repo_root / "scripts" / "build_pi_image.sh"
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    script = script_dir / "build_pi_image.sh"
    script.write_text(script_src.read_text())
    script.chmod(0o755)

    collect_src = repo_root / "scripts" / "collect_pi_image.sh"
    collect = script_dir / "collect_pi_image.sh"
    collect.write_text(collect_src.read_text())
    collect.chmod(0o755)

    telemetry_src = repo_root / "scripts" / "publish_telemetry.py"
    telemetry_script = script_dir / "publish_telemetry.py"
    telemetry_script.write_text(telemetry_src.read_text())
    telemetry_script.chmod(0o755)

    metadata_src = repo_root / "scripts" / "create_build_metadata.py"
    metadata_script = script_dir / "create_build_metadata.py"
    metadata_script.write_text(metadata_src.read_text())
    metadata_script.chmod(0o755)

    verifier_src = repo_root / "scripts" / "pi_node_verifier.sh"
    verifier = script_dir / "pi_node_verifier.sh"
    verifier.write_text(verifier_src.read_text())
    verifier.chmod(0o755)

    ci_dir = script_dir / "cloud-init"
    ci_dir.mkdir(parents=True)

    cloud_init_src = repo_root / "scripts" / "cloud-init"
    user_src = cloud_init_src / "user-data.yaml"
    shutil.copy(user_src, ci_dir / "user-data.yaml")

    compose_src = cloud_init_src / "docker-compose.cloudflared.yml"
    shutil.copy(compose_src, ci_dir / "docker-compose.cloudflared.yml")

    projects_src = cloud_init_src / "docker-compose.yml"
    shutil.copy(projects_src, ci_dir / "docker-compose.yml")

    start_projects_src = cloud_init_src / "start-projects.sh"
    start_projects_dest = ci_dir / "start-projects.sh"
    shutil.copy(start_projects_src, start_projects_dest)
    start_projects_dest.chmod(0o755)

    init_env_src = cloud_init_src / "init-env.sh"
    init_env_dest = ci_dir / "init-env.sh"
    shutil.copy(init_env_src, init_env_dest)
    init_env_dest.chmod(0o755)

    export_kubeconfig_src = cloud_init_src / "export-kubeconfig.sh"
    export_kubeconfig_dest = ci_dir / "export-kubeconfig.sh"
    shutil.copy(export_kubeconfig_src, export_kubeconfig_dest)
    export_kubeconfig_dest.chmod(0o755)

    export_node_token_src = cloud_init_src / "export-node-token.sh"
    export_node_token_dest = ci_dir / "export-node-token.sh"
    shutil.copy(export_node_token_src, export_node_token_dest)
    export_node_token_dest.chmod(0o755)

    apply_helm_src = cloud_init_src / "apply-helm-bundles.sh"
    apply_helm_dest = ci_dir / "apply-helm-bundles.sh"
    shutil.copy(apply_helm_src, apply_helm_dest)
    apply_helm_dest.chmod(0o755)

    k3s_ready_src = cloud_init_src / "k3s-ready.sh"
    k3s_ready_dest = ci_dir / "k3s-ready.sh"
    shutil.copy(k3s_ready_src, k3s_ready_dest)
    k3s_ready_dest.chmod(0o755)

    observability_src = cloud_init_src / "observability"
    if observability_src.exists():
        shutil.copytree(
            observability_src,
            ci_dir / "observability",
            dirs_exist_ok=True,
        )

    first_boot_src = repo_root / "scripts" / "first_boot_service.py"
    shutil.copy(first_boot_src, script_dir / "first_boot_service.py")
    (script_dir / "first_boot_service.py").chmod(0o755)

    self_heal_src = repo_root / "scripts" / "self_heal_service.py"
    shutil.copy(self_heal_src, script_dir / "self_heal_service.py")
    (script_dir / "self_heal_service.py").chmod(0o755)

    ssd_clone_src = repo_root / "scripts" / "ssd_clone.py"
    shutil.copy(ssd_clone_src, script_dir / "ssd_clone.py")
    (script_dir / "ssd_clone.py").chmod(0o755)

    ssd_clone_service_src = repo_root / "scripts" / "ssd_clone_service.py"
    shutil.copy(ssd_clone_service_src, script_dir / "ssd_clone_service.py")
    (script_dir / "ssd_clone_service.py").chmod(0o755)

    teams_src = repo_root / "scripts" / "sugarkube_teams.py"
    shutil.copy(teams_src, script_dir / "sugarkube_teams.py")
    (script_dir / "sugarkube_teams.py").chmod(0o755)

    token_place_replay_src = repo_root / "scripts" / "token_place_replay_samples.py"
    shutil.copy(token_place_replay_src, script_dir / "token_place_replay_samples.py")
    (script_dir / "token_place_replay_samples.py").chmod(0o755)

    systemd_src = repo_root / "scripts" / "systemd" / "first-boot.service"
    systemd_dir = script_dir / "systemd"
    systemd_dir.mkdir(exist_ok=True)
    shutil.copy(systemd_src, systemd_dir / "first-boot.service")

    ssd_clone_unit_src = repo_root / "scripts" / "systemd" / "ssd-clone.service"
    shutil.copy(ssd_clone_unit_src, systemd_dir / "ssd-clone.service")

    udev_src = repo_root / "scripts" / "udev" / "99-sugarkube-ssd-clone.rules"
    udev_dir = script_dir / "udev"
    udev_dir.mkdir(exist_ok=True)
    shutil.copy(udev_src, udev_dir / "99-sugarkube-ssd-clone.rules")

    extra_files = [
        ("scripts/spot_check.sh", 0o755),
        ("scripts/detect_target_disk.sh", 0o755),
        ("scripts/eeprom_nvme_first.sh", 0o755),
        ("scripts/clone_to_nvme.sh", 0o755),
        ("scripts/post_clone_verify.sh", 0o755),
        ("scripts/k3s_preflight.sh", 0o755),
        ("systemd/first-boot-prepare.sh", 0o755),
        ("systemd/first-boot-prepare.service", 0o644),
    ]
    for rel_path, mode in extra_files:
        src = repo_root / rel_path
        dest = tmp_path / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest)
        os.chmod(dest, mode)

    token_samples_src = repo_root / "samples" / "token_place"
    token_samples_dest = tmp_path / "samples" / "token_place"
    if token_samples_src.exists():
        shutil.copytree(token_samples_src, token_samples_dest, dirs_exist_ok=True)

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


def test_arm64_build_uses_release_branch(tmp_path):
    env = _setup_build_env(tmp_path)
    result, git_args = _run_build_script(tmp_path, env)
    assert result.returncode == 0
    assert "--branch bookworm" in git_args
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


def test_build_log_written_to_deploy(tmp_path):
    env = _setup_build_env(tmp_path)
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode == 0
    deploy_log = tmp_path / "deploy" / "sugarkube.build.log"
    assert deploy_log.exists()
    log_text = deploy_log.read_text()
    assert "[sugarkube] just command verified" in log_text
    host_log = tmp_path / "sugarkube.build.log"
    assert host_log.exists()
    assert host_log.read_text() == log_text


def test_build_copies_artifacts_to_deploy(tmp_path):
    env = _setup_build_env(tmp_path)
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode == 0

    deploy_dir = tmp_path / "deploy"
    image_path = tmp_path / "sugarkube.img.xz"
    deploy_image = deploy_dir / "sugarkube.img.xz"
    assert deploy_image.exists()
    assert image_path.exists()
    assert deploy_image.read_bytes() == image_path.read_bytes()

    checksum_path = tmp_path / "sugarkube.img.xz.sha256"
    deploy_checksum = deploy_dir / "sugarkube.img.xz.sha256"
    assert deploy_checksum.exists()
    assert checksum_path.exists()
    assert deploy_checksum.read_text() == checksum_path.read_text()

    metadata_path = tmp_path / "sugarkube.img.xz.metadata.json"
    stage_summary_path = tmp_path / "sugarkube.img.xz.stage-summary.json"
    deploy_metadata = deploy_dir / "sugarkube.img.xz.metadata.json"
    deploy_stage_summary = deploy_dir / "sugarkube.img.xz.stage-summary.json"

    assert metadata_path.exists()
    assert stage_summary_path.exists()
    assert deploy_metadata.exists()
    assert deploy_stage_summary.exists()
    assert deploy_metadata.read_text() == metadata_path.read_text()
    assert deploy_stage_summary.read_text() == stage_summary_path.read_text()


def test_repo_collect_step_finds_deploy_artifacts(tmp_path):
    env = _setup_build_env(tmp_path)
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode == 0

    deploy_dir = tmp_path / "deploy"
    assert (deploy_dir / "sugarkube.img.xz").exists()

    # Remove the host copies to ensure collect_pi_image.sh relies on deploy/
    (tmp_path / "sugarkube.img.xz").unlink()
    (tmp_path / "sugarkube.img.xz.sha256").unlink()

    collect_script = Path(__file__).resolve().parents[1] / "scripts" / "collect_pi_image.sh"
    result = subprocess.run(
        ["/bin/bash", str(collect_script), "deploy", "./sugarkube.img.xz"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={"PATH": os.environ["PATH"], "MAX_SCAN_DEPTH": "6"},
    )
    assert result.returncode == 0, result.stderr

    rebuilt = tmp_path / "sugarkube.img.xz"
    rebuilt_sha = tmp_path / "sugarkube.img.xz.sha256"
    assert rebuilt.exists()
    assert rebuilt_sha.exists()


def test_build_log_handles_nested_layout(tmp_path):
    env = _setup_build_env(tmp_path, nested_log=True)
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode == 0
    deploy_log = tmp_path / "deploy" / "sugarkube.build.log"
    assert deploy_log.exists()
    log_text = deploy_log.read_text()
    assert "[sugarkube] just command verified" in log_text
    assert "logs/2025-10-31/build.log" in log_text
    host_log = tmp_path / "sugarkube.build.log"
    assert host_log.exists()
    assert host_log.read_text() == log_text


def test_build_log_handles_compressed_logs(tmp_path):
    env = _setup_build_env(tmp_path, compressed_log=True)
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode == 0
    deploy_log = tmp_path / "deploy" / "sugarkube.build.log"
    assert deploy_log.exists()
    log_text = deploy_log.read_text()
    assert "[sugarkube] just command verified" in log_text
    assert "build.log.xz" in log_text
    host_log = tmp_path / "sugarkube.build.log"
    assert host_log.exists()
    assert host_log.read_text() == log_text


def test_build_log_handles_gzip_logs(tmp_path):
    env = _setup_build_env(tmp_path, gzip_log=True)
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode == 0
    deploy_log = tmp_path / "deploy" / "sugarkube.build.log"
    assert deploy_log.exists()
    log_text = deploy_log.read_text()
    assert "[sugarkube] just command verified" in log_text
    assert "build.log.gz" in log_text
    host_log = tmp_path / "sugarkube.build.log"
    assert host_log.exists()
    assert host_log.read_text() == log_text


def test_build_log_recovers_stage_just_log(tmp_path):
    env = _setup_build_env(tmp_path, stage_log=True)
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode == 0
    deploy_log = tmp_path / "deploy" / "sugarkube.build.log"
    assert deploy_log.exists()
    log_text = deploy_log.read_text()
    assert "[sugarkube] just command verified" in log_text
    assert "stage log appended" in log_text
    host_log = tmp_path / "sugarkube.build.log"
    assert host_log.exists()
    assert host_log.read_text() == log_text


def test_installs_ssd_clone_service(tmp_path):
    env = _setup_build_env(tmp_path)
    env["KEEP_WORK_DIR"] = "1"
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode == 0
    match = re.search(r"leaving work dir: (?P<path>\S+)", result.stdout)
    assert match, result.stdout
    work_dir = Path(match.group("path"))
    stage_root = work_dir / "pi-gen" / "stage2" / "01-sys-tweaks" / "files"
    assert (stage_root / "opt" / "sugarkube" / "ssd_clone.py").exists()
    assert (stage_root / "opt" / "sugarkube" / "ssd_clone_service.py").exists()
    assert (stage_root / "opt" / "sugarkube" / "sugarkube_teams.py").exists()
    assert (stage_root / "usr" / "local" / "bin" / "sugarkube-teams").exists()
    service_path = stage_root / "etc" / "systemd" / "system" / "ssd-clone.service"
    assert service_path.exists()
    wants_link = (
        stage_root / "etc" / "systemd" / "system" / "multi-user.target.wants" / "ssd-clone.service"
    )
    assert not wants_link.exists()
    udev_rule = stage_root / "etc" / "udev" / "rules.d" / "99-sugarkube-ssd-clone.rules"
    assert udev_rule.exists()
    shutil.rmtree(work_dir)
    assert not (tmp_path / "sugarkube.img.xz.xz").exists()


def test_configurable_mirror_failover(tmp_path):
    env = _setup_build_env(tmp_path)
    env["KEEP_WORK_DIR"] = "1"
    env["APT_REWRITE_MIRRORS"] = (
        "https://primary.example.invalid/raspbian " "https://secondary.example.invalid/raspbian"
    )

    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode == 0

    match = re.search(r"leaving work dir: (?P<path>\S+)", result.stdout)
    assert match, result.stdout
    work_dir = Path(match.group("path"))

    rewrite_script = (
        work_dir
        / "pi-gen"
        / "stage0"
        / "00-configure-apt"
        / "files"
        / "usr"
        / "local"
        / "sbin"
        / "apt-rewrite-mirrors"
    ).read_text()
    assert "https://primary.example.invalid/raspbian" in rewrite_script
    assert "https://secondary.example.invalid/raspbian" in rewrite_script

    stage0_retry = (work_dir / "pi-gen" / "stage0" / "00-configure-apt" / "01-run.sh").read_text()
    assert "https://primary.example.invalid/raspbian" in stage0_retry
    assert "https://secondary.example.invalid/raspbian" in stage0_retry
    assert "try_mirrors=" in stage0_retry

    stage2_retry = (work_dir / "pi-gen" / "stage2" / "00-configure-apt" / "01-run.sh").read_text()
    assert "https://secondary.example.invalid/raspbian" in stage2_retry

    export_retry = (
        work_dir / "pi-gen" / "export-image" / "02-set-sources" / "02-run.sh"
    ).read_text()
    assert "https://secondary.example.invalid/raspbian" in export_retry

    shutil.rmtree(work_dir)


def test_arm64_disables_armhf(tmp_path):
    env = _setup_build_env(tmp_path)
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode == 0
    config = (tmp_path / "config.env").read_text()
    assert "ARM64=1" in config
    assert "ARMHF=0" in config


def test_armhf_enabled_for_32_bit(tmp_path):
    env = _setup_build_env(tmp_path)
    env["ARM64"] = "0"
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode == 0
    config = (tmp_path / "config.env").read_text()
    assert "ARM64=0" in config
    assert "ARMHF=1" in config


def test_build_without_timeout_binary(tmp_path):
    env = _setup_build_env(tmp_path)
    fake_bin = Path(env["PATH"].split(":")[0])
    (fake_bin / "timeout").unlink()
    (fake_bin / "python3").write_text("#!/bin/sh\nexit 0\n")
    (fake_bin / "python3").chmod(0o755)
    # Remove system PATH so timeout is truly absent
    env["PATH"] = str(fake_bin)
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode != 0
    assert "timeout is required" in result.stderr


def test_build_without_stdbuf_binary(tmp_path):
    env = _setup_build_env(tmp_path)
    fake_bin = Path(env["PATH"].split(":")[0])
    (fake_bin / "stdbuf").unlink()
    (fake_bin / "python3").write_text("#!/bin/sh\nexit 0\n")
    (fake_bin / "python3").chmod(0o755)
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


@pytest.mark.skipif(os.geteuid() != 0, reason="requires root to exercise safe.directory handling")
def test_marks_repo_safe_directory_for_root(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    gitconfig = tmp_path / "gitconfig"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    docker_stub = fake_bin / "docker"
    docker_stub.write_text("#!/bin/sh\nexit 0\n")
    docker_stub.chmod(0o755)
    bsdtar_stub = fake_bin / "bsdtar"
    bsdtar_stub.write_text("#!/bin/sh\nexit 0\n")
    bsdtar_stub.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "GIT_CONFIG_SYSTEM": str(gitconfig),
            "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig.global"),
            "SKIP_BINFMT": "1",
            "SKIP_URL_CHECK": "1",
            "SKIP_CLOUD_INIT_VALIDATION": "1",
            "SKIP_MIRROR_REWRITE": "1",
            "CLOUD_INIT_PATH": str(tmp_path / "missing-user-data.yaml"),
        }
    )

    result = subprocess.run(
        ["/bin/bash", str(repo_root / "scripts/build_pi_image.sh")],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Cloud-init file not found" in result.stderr

    assert gitconfig.exists(), "git config --system should have written to the temp file"
    config_text = gitconfig.read_text()
    assert "[safe]" in config_text
    assert f"directory = {repo_root}" in config_text


def test_requires_stage_list(tmp_path):
    env = _setup_build_env(tmp_path)
    env["PI_GEN_STAGES"] = "   "
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode != 0
    assert "PI_GEN_STAGES must include at least one stage" in result.stderr


def test_powershell_script_mentions_cloudflared_compose():
    text = Path("scripts/build_pi_image.ps1").read_text()
    assert "docker-compose.cloudflared.yml" in text


def test_user_data_installs_k3s():
    text = Path("scripts/cloud-init/user-data.yaml").read_text()
    assert "https://get.k3s.io" in text
