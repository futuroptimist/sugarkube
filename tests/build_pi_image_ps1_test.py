import subprocess


def test_ps1_has_entrypoint_banner():
    # Guard against the script silently exiting without running
    pattern = r"\[sugarkube\] Starting Raspberry Pi image build"
    result = subprocess.run(
        [
            "/usr/bin/env",
            "bash",
            "-lc",
            f"grep -q '{pattern}' scripts/build_pi_image.ps1",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
