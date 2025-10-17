from __future__ import annotations

import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "migrate_to_nvme.sh"


def _write_stub(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(stat.S_IRWXU)


@pytest.fixture()
def stubbed_commands(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    call_log = tmp_path / "calls.log"
    call_log.write_text("", encoding="utf-8")

    def mk_stub(name: str, content: str) -> Path:
        path = bin_dir / name
        _write_stub(path, content)
        return path

    mk_stub(
        "spot_check.sh",
        textwrap.dedent(
            """
            #!/usr/bin/env bash
            echo "spot-check:$*" >>"${CALL_LOG}"
            """
        ),
    )
    mk_stub(
        "eeprom.sh",
        textwrap.dedent(
            """
            #!/usr/bin/env bash
            echo "eeprom:$*" >>"${CALL_LOG}"
            """
        ),
    )
    mk_stub(
        "clone_stub.sh",
        textwrap.dedent(
            """
            #!/usr/bin/env bash
            echo "clone:${TARGET:-}:${WIPE:-}:$*" >>"${CALL_LOG}"
            """
        ),
    )
    mk_stub(
        "reboot",
        textwrap.dedent(
            """
            #!/usr/bin/env bash
            echo "reboot" >>"${CALL_LOG}"
            """
        ),
    )
    mk_stub(
        "sync",
        textwrap.dedent(
            """
            #!/usr/bin/env bash
            echo "sync" >>"${CALL_LOG}"
            """
        ),
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "CALL_LOG": str(call_log),
            "SPOT_CHECK_CMD": str(bin_dir / "spot_check.sh"),
            "EEPROM_CMD": str(bin_dir / "eeprom.sh"),
            "CLONE_CMD": str(bin_dir / "clone_stub.sh"),
            "MIGRATE_ARTIFACTS": str(tmp_path / "artifacts"),
            "CLONE_TARGET": "/dev/nvme0n1",
            "CLONE_WIPE": "1",
        }
    )

    return env, call_log, tmp_path / "artifacts" / "migrate.log"


def test_full_migration_flow(stubbed_commands: tuple[dict[str, str], Path, Path]) -> None:
    env, call_log, log_file = stubbed_commands
    result = subprocess.run([str(SCRIPT)], capture_output=True, text=True, env=env)
    assert result.returncode == 0
    calls = call_log.read_text(encoding="utf-8").strip().splitlines()
    assert calls == [
        "spot-check:",
        "eeprom:",
        "clone:/dev/nvme0n1:1:",
        "sync",
        "reboot",
    ]
    assert log_file.exists()
    log_contents = log_file.read_text(encoding="utf-8")
    assert "[migrate] >>> spot-check" in log_contents
    assert "[migrate] >>> eeprom" in log_contents
    assert "[migrate] >>> clone" in log_contents
    assert "Log captured" in log_contents


def test_skip_eeprom_and_reboot(stubbed_commands: tuple[dict[str, str], Path, Path]) -> None:
    env, call_log, log_file = stubbed_commands
    env["SKIP_EEPROM"] = "1"
    env["NO_REBOOT"] = "1"
    call_log.write_text("", encoding="utf-8")
    result = subprocess.run([str(SCRIPT)], capture_output=True, text=True, env=env)
    assert result.returncode == 0
    calls = call_log.read_text(encoding="utf-8").strip().splitlines()
    assert calls == [
        "spot-check:",
        "clone:/dev/nvme0n1:1:",
    ]
    log_contents = log_file.read_text(encoding="utf-8")
    assert "SKIP_EEPROM=1" in log_contents
    assert "NO_REBOOT=1" in log_contents


def test_failure_bubbles_up(stubbed_commands: tuple[dict[str, str], Path, Path]) -> None:
    env, call_log, _ = stubbed_commands
    failing = Path(env["SPOT_CHECK_CMD"])
    _write_stub(
        failing,
        textwrap.dedent(
            """
            #!/usr/bin/env bash
            echo "spot-check:$*" >>"${CALL_LOG}"
            exit 3
            """
        ),
    )
    result = subprocess.run([str(SCRIPT)], capture_output=True, text=True, env=env)
    assert result.returncode == 3
    calls = call_log.read_text(encoding="utf-8").strip().splitlines()
    assert calls == ["spot-check:"]
