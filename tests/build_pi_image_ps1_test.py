import subprocess


def test_ps1_has_entrypoint_banner():
    """Ensure the PS1 script prints its startup banner.

    Prevent regressions where the PS1 script only defines functions and exits silently.
    """
    result = subprocess.run(
        [
            "/usr/bin/env",
            "bash",
            "-lc",
            (
                r"grep -q '\[sugarkube\] Starting Raspberry Pi image build' "
                "scripts/build_pi_image.ps1"
            ),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
