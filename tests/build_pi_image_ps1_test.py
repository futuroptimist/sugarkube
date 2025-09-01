import subprocess


def test_ps1_has_entrypoint_banner():
    """Ensure PowerShell entrypoint prints a starting message."""
    cmd = [
        "/usr/bin/env",
        "bash",
        "-lc",
        (
            "grep -q '\\[sugarkube\\] Starting Raspberry Pi image build' "
            "scripts/build_pi_image.ps1"
        ),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
