import subprocess


def test_ps1_has_entrypoint_banner():
    """Ensure the PS1 script prints a startup banner."""
    cmd = (
        r"grep -q '\[sugarkube\] Starting Raspberry Pi image build' "
        "scripts/build_pi_image.ps1"
    )
    result = subprocess.run(
        ["/usr/bin/env", "bash", "-lc", cmd],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
