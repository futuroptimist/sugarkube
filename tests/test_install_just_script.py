"""Regression coverage for scripts/install_just.sh."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from tests.support import just_installer
from tests.support.just_installer import ensure_just_available


def test_install_just_installs_binary(tmp_path: Path) -> None:
    """The installer should download and validate the just binary."""

    prefix = tmp_path / "bin"
    env = os.environ.copy()
    env["JUST_INSTALL_PREFIX"] = str(prefix)
    installer = Path(__file__).resolve().parents[1] / "scripts" / "install_just.sh"

    result = subprocess.run(
        ["bash", str(installer)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    just_path = prefix / "just"
    assert just_path.exists()
    assert just_path.stat().st_mode & 0o111

    version = subprocess.check_output([str(just_path), "--version"], text=True)
    assert "just" in version


def test_just_installer_helper_reuses_existing_binary(monkeypatch) -> None:
    """ensure_just_available should short-circuit when just already exists."""

    path_dir = Path(tempfile.mkdtemp(prefix="just-path-"))
    fake_just = path_dir / "just"
    fake_just.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_just.chmod(0o755)

    monkeypatch.setenv("PATH", f"{path_dir}")

    resolved = ensure_just_available()
    assert resolved == fake_just

    just_installer._JUST_PATH = None

    fake_just.unlink(missing_ok=True)
    path_dir.rmdir()
    monkeypatch.delenv("PATH", raising=False)
