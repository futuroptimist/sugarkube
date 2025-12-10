"""Validate the portable just installer."""

from __future__ import annotations

import os
import subprocess
import tarfile
from pathlib import Path


def test_install_just_uses_custom_tarball(tmp_path: Path) -> None:
    installer = Path(__file__).resolve().parents[1] / "scripts" / "install_just.sh"

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    just_stub = tmp_path / "just"
    just_stub.write_text("#!/usr/bin/env bash\necho installer-$1\n", encoding="utf-8")
    just_stub.chmod(0o755)

    tarball = tmp_path / "just.tar.gz"
    with tarfile.open(tarball, "w:gz") as archive:
        archive.add(just_stub, arcname="just")

    env = os.environ.copy()
    env["SUGARKUBE_JUST_BIN_DIR"] = str(bin_dir)
    env["SUGARKUBE_JUST_TARBALL"] = str(tarball)
    env["SUGARKUBE_JUST_FORCE_INSTALL"] = "1"

    result = subprocess.run(
        ["/bin/bash", str(installer)],
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    installed = bin_dir / "just"
    assert installed.exists(), "Installer should place the binary in the requested bin dir"
    assert installed.stat().st_mode & 0o111, "Installed just should be executable"

    exec_result = subprocess.run(
        [str(installed), "--version"], capture_output=True, text=True, check=False
    )
    assert "installer" in exec_result.stdout
