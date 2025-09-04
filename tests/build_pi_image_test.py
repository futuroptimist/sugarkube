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
        "bsdtar",
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
    for name in [
        "curl",
        "docker",
        "git",
        "sha256sum",
        "stdbuf",
        "timeout",
        "bsdtar",
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
    for name in ["xz", "git", "sha256sum", "bsdtar"]:
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


#cloud-config
package_update: true
package_upgrade: true
apt:
  sources:
    cloudflare:
      source: "deb [arch=arm64] https://pkg.cloudflare.com/ bookworm main"
      keyid: FBA8C0EE63617C5EED695C43254B391D8CACCBF8
      keyserver: https://keyserver.ubuntu.com
packages:
  - docker.io
  - docker-compose-plugin
  - curl
  - git
  - cloudflared
write_files:
  - path: /opt/sugarkube/.cloudflared.env
    permissions: '0600'
    content: |
      # Inject with TUNNEL_TOKEN or TUNNEL_TOKEN_FILE env var or edit after boot
      TUNNEL_TOKEN=""
  - path: /etc/systemd/system/cloudflared-compose.service
    permissions: '0644'
    content: |
      [Unit]
      Description=Cloudflare Tunnel via docker compose
      Requires=docker.service
      After=docker.service network-online.target
      Wants=network-online.target

      [Service]
      Type=oneshot
      WorkingDirectory=/opt/sugarkube
      ExecStart=/usr/bin/docker compose -f /opt/sugarkube/docker-compose.cloudflared.yml up -d
      ExecStop=/usr/bin/docker compose -f /opt/sugarkube/docker-compose.cloudflared.yml down
      RemainAfterExit=yes
      Restart=on-failure
      RestartSec=5s

      [Install]
      WantedBy=multi-user.target
  - path: /etc/apt/apt.conf.d/80-retries
    permissions: '0644'
    content: |
      Acquire::Retries "5";
      Acquire::http::Timeout "30";
      Acquire::https::Timeout "30";
  - path: /opt/projects/token.place/docker-compose.tokenplace.yml
    permissions: '0644'
    content: |
      version: '3'
      services:
        tokenplace:
          build:
            context: /opt/projects/token.place
            dockerfile: docker/Dockerfile.server
          ports:
            - "5000:5000"
  - path: /etc/systemd/system/tokenplace.service
    permissions: '0644'
    content: |
      [Unit]
      Description=token.place server via docker compose
      Requires=docker.service
      After=docker.service network-online.target
      Wants=network-online.target

      [Service]
      Type=oneshot
      WorkingDirectory=/opt/projects/token.place
      ExecStart=/usr/bin/docker compose -f docker-compose.tokenplace.yml up -d
      ExecStop=/usr/bin/docker compose -f docker-compose.tokenplace.yml down
      RemainAfterExit=yes
      Restart=on-failure
      RestartSec=5s

      [Install]
      WantedBy=multi-user.target
  - path: /etc/systemd/system/dspace.service
    permissions: '0644'
    content: |
      [Unit]
      Description=dspace frontend via docker compose
      Requires=docker.service
      After=docker.service network-online.target
      Wants=network-online.target

      [Service]
      Type=oneshot
      WorkingDirectory=/opt/projects/dspace/frontend
      ExecStartPre=-/usr/bin/cp -n .env.example .env
      ExecStart=/usr/bin/docker compose up -d
      ExecStop=/usr/bin/docker compose down
      RemainAfterExit=yes
      Restart=on-failure
      RestartSec=5s

      [Install]
      WantedBy=multi-user.target
runcmd:
  - [bash, -c, 'id pi >/dev/null 2>&1 && usermod -aG docker pi || true']
  - [bash, -c, 'mkdir -p /opt/sugarkube']
  - [bash, -c, 'id pi >/dev/null 2>&1 && chown -R pi:pi /opt/sugarkube || true']
  - [systemctl, daemon-reexec]   # reload systemd units
  - [systemctl, enable, --now, docker]
  - [systemctl, enable, --now, tokenplace.service]
  - [systemctl, enable, --now, dspace.service]
  - [bash, -c, 'apt-get clean && rm -rf /var/lib/apt/lists/*']
  - |
      if grep -q 'TUNNEL_TOKEN=""' /opt/sugarkube/.cloudflared.env; then
        echo 'Cloudflare token missing; not starting tunnel'
      else
        systemctl enable --now cloudflared-compose.service
      fi


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

    verifier_src = repo_root / "scripts" / "pi_node_verifier.sh"
    verifier = script_dir / "pi_node_verifier.sh"
    verifier.write_text(verifier_src.read_text())
    verifier.chmod(0o755)

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
    assert not (tmp_path / "sugarkube.img.xz.xz").exists()


def test_copies_cloudflared_compose(tmp_path):
    env = _setup_build_env(tmp_path, check_compose=True)
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode == 0


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


def test_requires_cloudflared_compose_file(tmp_path):
    env = _setup_build_env(tmp_path)
    env["CLOUDFLARED_COMPOSE_PATH"] = str(tmp_path / "missing.yml")
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode != 0
    assert "Cloudflared compose file not found" in result.stderr


def test_requires_stage_list(tmp_path):
    env = _setup_build_env(tmp_path)
    env["PI_GEN_STAGES"] = "   "
    result, _ = _run_build_script(tmp_path, env)
    assert result.returncode != 0
    assert "PI_GEN_STAGES must include at least one stage" in result.stderr


def test_powershell_script_mentions_cloudflared_compose():
    text = Path("scripts/build_pi_image.ps1").read_text()
    assert "docker-compose.cloudflared.yml" in text
