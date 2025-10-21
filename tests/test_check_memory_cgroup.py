from __future__ import annotations

import os
import stat
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_memory_cgroup.sh"


def _make_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(stat.S_IRWXU)


def test_skip_on_non_linux_host(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    call_log = tmp_path / "sudo.log"
    call_log.write_text("", encoding="utf-8")

    _make_executable(
        bin_dir / "uname",
        "#!/usr/bin/env bash\necho Darwin\n",
    )
    _make_executable(
        bin_dir / "sudo",
        textwrap.dedent(
            """
            #!/usr/bin/env bash
            echo "sudo:$*" >>"${CALL_LOG}"
            exit 42
            """
        ),
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "CALL_LOG": str(call_log),
            "EUID": "1000",
        }
    )

    completed = subprocess.run(
        [str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0
    assert "Non-Linux host detected; skipping memory cgroup configuration." in completed.stdout
    assert call_log.read_text(encoding="utf-8").strip() == ""


def test_happy_path_updates_cmdline_and_reboots(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    call_log = tmp_path / "calls.log"
    call_log.write_text("", encoding="utf-8")

    def make_stub(name: str, body: str) -> None:
        _make_executable(
            bin_dir / name,
            textwrap.dedent(
                f"""
                #!/usr/bin/env bash
                {body}
                """
            ),
        )

    make_stub("uname", "echo Linux")
    make_stub("systemctl", "echo \"systemctl:$*\" >>\"${CALL_LOG}\"")
    make_stub("sleep", "echo \"sleep:$*\" >>\"${CALL_LOG}\"")
    make_stub("sync", "echo sync >>\"${CALL_LOG}\"")

    state_dir = tmp_path / "state"
    systemd_dir = tmp_path / "systemd"
    systemd_dir.mkdir(parents=True)

    cmdline = tmp_path / "boot" / "firmware" / "cmdline.txt"
    cmdline.parent.mkdir(parents=True)
    cmdline.write_text(
        (
            "console=serial0,115200 console=tty1 root=LABEL=w00t rootfstype=ext4 "
            "fsck.repair=yes rootwait cgroup_disable=memory\n"
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "CALL_LOG": str(call_log),
            "EUID": "0",
            "SUGARKUBE_MEMCTRL_FORCE": "inactive",
            "SUGARKUBE_CMDLINE_PATH": str(cmdline),
            "SUGARKUBE_STATE_DIR": str(state_dir),
            "SUGARKUBE_SYSTEMD_DIR": str(systemd_dir),
            "SUDO_USER": "pi",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_SERVERS": "pi-cluster",
            "SUGARKUBE_TOKEN_DEV": "dev-token",
        }
    )

    completed = subprocess.run(
        [str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0
    assert "Rebooting now to apply kernel parameters" in completed.stdout

    updated = cmdline.read_text(encoding="utf-8").strip()
    assert "cgroup_memory=1" in updated
    assert "cgroup_enable=memory" in updated
    assert "cgroup_disable=memory" not in updated
    assert updated.count("cgroup_memory=1") == 1
    assert updated.count("cgroup_enable=memory") == 1

    backups = list(cmdline.parent.glob("cmdline.txt.bak.*"))
    assert len(backups) == 1

    env_file = state_dir / "env"
    assert env_file.exists()
    env_contents = env_file.read_text(encoding="utf-8")
    assert "SUGARKUBE_ENV=dev" in env_contents
    assert "SUGARKUBE_SERVERS=pi-cluster" in env_contents
    assert "SUGARKUBE_TOKEN_DEV=dev-token" in env_contents
    assert "SUGARKUBE_TOKEN=dev-token" in env_contents

    service = systemd_dir / "sugarkube-post-reboot.service"
    assert service.exists()
    service_contents = service.read_text(encoding="utf-8")
    assert "EnvironmentFile=" + str(env_file) in service_contents
    assert "WorkingDirectory=/home/pi/sugarkube" in service_contents
    assert "ExecStart=/usr/bin/just up dev" in service_contents

    calls = call_log.read_text(encoding="utf-8").strip().splitlines()
    assert calls == [
        "sync",
        "systemctl:daemon-reload",
        "systemctl:enable sugarkube-post-reboot.service",
        "sleep:2",
        "systemctl:reboot",
    ]

    assert "removed: cgroup_disable=memory" in completed.stderr
