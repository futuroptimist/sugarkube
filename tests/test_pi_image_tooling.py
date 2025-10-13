"""Regression tests for Pi image tooling additions."""

from __future__ import annotations

import re
from pathlib import Path

from tests import build_pi_image_test as build_test


def _extract_work_dir(stdout: str) -> Path:
    match = re.search(r"leaving work dir: (?P<path>\S+)", stdout)
    assert match, stdout
    return Path(match.group("path"))


def test_just_installation_script_includes_fallback(tmp_path):
    env = build_test._setup_build_env(tmp_path)
    env["KEEP_WORK_DIR"] = "1"
    result, _ = build_test._run_build_script(tmp_path, env)
    assert result.returncode == 0

    work_dir = _extract_work_dir(result.stdout)
    script_path = work_dir / "pi-gen" / "stage2" / "01-sys-tweaks" / "03-run-chroot-just.sh"
    assert script_path.exists(), script_path
    script_text = script_path.read_text()

    assert 'apt-get "${APT_OPTS[@]}" install -y --no-install-recommends just' in script_text
    assert "https://just.systems/install.sh" in script_text
    assert "✅ just command verified" in script_text
    assert "just --version" in script_text
    assert "just --list" in script_text

    profile_path = (
        work_dir
        / "pi-gen"
        / "stage2"
        / "01-sys-tweaks"
        / "files"
        / "etc"
        / "profile.d"
        / "sugarkube-path.sh"
    )
    assert profile_path.exists(), profile_path
    profile_text = profile_path.read_text()
    assert "/usr/local/bin" in profile_text
    assert "export PATH" in profile_text
