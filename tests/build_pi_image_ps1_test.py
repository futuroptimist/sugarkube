import subprocess


def test_ps1_has_entrypoint_banner():
    """Ensure the PowerShell script shows the start banner."""
    grep_cmd = (
        r"grep -q '\[sugarkube\] Starting Raspberry Pi image build' "
        "scripts/build_pi_image.ps1"
    )
    result = subprocess.run(
        [
            "/usr/bin/env",
            "bash",
            "-lc",
            grep_cmd,
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
