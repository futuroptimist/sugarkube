from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "boot_order.sh"


@pytest.fixture()
def stub_env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    apply_path = tmp_path / "applied.conf"

    rpi_eeprom = bin_dir / "rpi-eeprom-config"
    rpi_eeprom.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
APPLY_PATH=""" + str(apply_path) + """
if [[ $# -gt 0 && $1 == --apply ]]; then
  cp "$2" "${APPLY_PATH}"
  exit 0
fi
cat <<'CFG'
BOOT_ORDER=0xF416
PCIE_PROBE=0
CFG
""",
        encoding="utf-8",
    )
    rpi_eeprom.chmod(stat.S_IRWXU)

    sudo = bin_dir / "sudo"
    sudo.write_text("#!/usr/bin/env bash\nexec \"$@\"\n", encoding="utf-8")
    sudo.chmod(stat.S_IRWXU)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["TEST_APPLY_PATH"] = str(apply_path)
    return env


def _read_applied(env: dict[str, str]) -> str:
    return Path(env["TEST_APPLY_PATH"]).read_text(encoding="utf-8")


def test_preset_sd_nvme_usb(tmp_path: Path, stub_env: dict[str, str]) -> None:
    env = stub_env
    result = subprocess.run(
        [str(SCRIPT), "preset", "sd-nvme-usb"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    assert "Target preset 'sd-nvme-usb'" in result.stdout
    applied = _read_applied(env)
    assert "boot_order=0xf461" in applied.lower()
    assert "PCIE_PROBE=1" not in applied


def test_preset_honours_pcie_probe(tmp_path: Path, stub_env: dict[str, str]) -> None:
    env = stub_env
    env["PCIE_PROBE"] = "1"
    result = subprocess.run(
        [str(SCRIPT), "preset", "nvme-first"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    assert "Target preset 'nvme-first'" in result.stdout
    applied = _read_applied(env)
    assert "boot_order=0xf416" in applied.lower()
    assert "PCIE_PROBE=1" in applied


def test_preset_rejects_unknown(tmp_path: Path, stub_env: dict[str, str]) -> None:
    env = stub_env
    completed = subprocess.run(
        [str(SCRIPT), "preset", "not-real"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    assert "Unknown boot-order preset" in completed.stderr
