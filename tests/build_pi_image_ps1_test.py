import subprocess


def test_ps1_has_entrypoint_banner():
    """Ensure the PowerShell build script has a visible entrypoint."""
    cmd = [
        "/usr/bin/env",
        "bash",
        "-lc",
        (
            r"grep -q '\[sugarkube\] Starting Raspberry Pi image build' "
            r"scripts/build_pi_image.ps1"
        ),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
