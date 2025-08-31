"""Tests for the PowerShell image builder script."""

import subprocess


def test_ps1_has_entrypoint_banner():
    """Ensure the build script starts with a visible banner."""

    result = subprocess.run(
        [
            "grep",
            "-qF",
            "[sugarkube] Starting Raspberry Pi image build",
            "scripts/build_pi_image.ps1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
