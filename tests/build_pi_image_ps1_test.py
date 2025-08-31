import subprocess


def test_ps1_has_entrypoint_banner():
    # Ensure the entrypoint prints a banner and doesn't exit silently
    command = (
        r"grep -q '\[sugarkube\] Starting Raspberry Pi image build' "
        "scripts/build_pi_image.ps1"
    )
    result = subprocess.run(
        ["/usr/bin/env", "bash", "-lc", command],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
