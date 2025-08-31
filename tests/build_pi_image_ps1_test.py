import subprocess


def test_ps1_has_entrypoint_banner():
    # Prevent regressions where the PS1 script only defines functions
    # and exits silently
    banner = "[sugarkube] Starting Raspberry Pi image build"
    cmd = [
        "/usr/bin/env",
        "bash",
        "-lc",
        f"grep -Fq '{banner}' scripts/build_pi_image.ps1",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
