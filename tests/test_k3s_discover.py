from __future__ import annotations

import os
import stat
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "k3s-discover.sh"


def _make_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    path.chmod(stat.S_IRWXU)


def _prepare_stubbed_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    call_log = tmp_path / "calls.log"
    call_log.write_text("", encoding="utf-8")

    _make_executable(
        bin_dir / "hostname",
        """#!/usr/bin/env bash
        echo "hostname:$*" >>"${CALL_LOG}"
        if [ "$#" -gt 0 ]; then
          shift
        fi
        echo sugarkube0
        """,
    )

    _make_executable(
        bin_dir / "avahi-browse",
        """#!/usr/bin/env bash
        echo "avahi-browse:$*" >>"${CALL_LOG}"
        exit 0
        """,
    )

    _make_executable(
        bin_dir / "sudo",
        """#!/usr/bin/env bash
        echo "sudo:$*" >>"${CALL_LOG}"
        while [ "$#" -gt 0 ]; do
          case "$1" in
            -E|-H|-n)
              shift
              ;;
            --preserve-env|--preserve-env=*)
              shift
              ;;
            --)
              shift
              break
              ;;
            -* )
              shift
              ;;
            *)
              break
              ;;
          esac
        done
        if [ "$#" -eq 0 ]; then
          exit 0
        fi
        exec "$@"
        """,
    )

    _make_executable(
        bin_dir / "systemctl",
        """#!/usr/bin/env bash
        echo "systemctl:$*" >>"${CALL_LOG}"
        exit 0
        """,
    )

    _make_executable(
        bin_dir / "sleep",
        """#!/usr/bin/env bash
        echo "sleep:$*" >>"${CALL_LOG}"
        exit 0
        """,
    )

    _make_executable(
        bin_dir / "curl",
        """#!/usr/bin/env bash
        echo "curl:$*" >>"${CALL_LOG}"
        cat <<'SCRIPT'
#!/usr/bin/env bash
echo "install-env:INSTALL_K3S_CHANNEL=${INSTALL_K3S_CHANNEL:-}" >>"${CALL_LOG}"
echo "install-env:K3S_TOKEN=${K3S_TOKEN:-}" >>"${CALL_LOG}"
printf 'install-args:' >>"${CALL_LOG}"
for arg in "$@"; do
  printf ' %s' "$arg" >>"${CALL_LOG}"
done
echo >>"${CALL_LOG}"
exit 0
SCRIPT
        """,
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "CALL_LOG": str(call_log),
        }
    )

    return env, call_log


def test_uses_local_node_token_when_available(tmp_path: Path) -> None:
    env, call_log = _prepare_stubbed_env(tmp_path)

    token_path = tmp_path / "state" / "node-token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("DEV_TOKEN_123\n", encoding="utf-8")

    avahi_dir = tmp_path / "avahi"

    env.update(
        {
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_SERVERS": "1",
            "SUGARKUBE_TOKEN_PATH_HINTS": str(token_path),
            "SUGARKUBE_AVAHI_SERVICES_DIR": str(avahi_dir),
            "SUGARKUBE_CLUSTER": "sugar",
        }
    )
    env.pop("SUGARKUBE_TOKEN", None)
    env.pop("SUGARKUBE_TOKEN_DEV", None)

    completed = subprocess.run(
        [str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert f"Using join token from {token_path}" in completed.stdout

    calls = call_log.read_text(encoding="utf-8").splitlines()
    assert any("install-env:K3S_TOKEN=DEV_TOKEN_123" in line for line in calls)


def test_errors_when_no_token_found(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.update(
        {
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_SERVERS": "1",
            "PATH": env["PATH"],
        }
    )
    env.pop("SUGARKUBE_TOKEN", None)
    env.pop("SUGARKUBE_TOKEN_DEV", None)

    completed = subprocess.run(
        [str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "SUGARKUBE_TOKEN (or per-env variant) required" in completed.stdout
