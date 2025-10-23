import subprocess
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh")


def test_require_activity_logs_use_effective_attempts(tmp_path):
    # empty fixture: no adverts, triggers the grace window then exit that block
    fixture = tmp_path / "empty_mdns.txt"
    fixture.write_text("", encoding="utf-8")

    env = {
        "SUGARKUBE_CLUSTER": "sugar",
        "SUGARKUBE_ENV": "dev",
        "DISCOVERY_ATTEMPTS": "15",
        "DISCOVERY_WAIT_SECS": "0",
        "SUGARKUBE_MDNS_FIXTURE_FILE": str(fixture),
        # Speed up the path: prevent random jitter pause by skipping to election quickly
        "SUGARKUBE_TOKEN": "dummy",  # unblock token check
        "SUGARKUBE_RUNTIME_DIR": str(tmp_path / "run"),
    }

    # Run just the wait-loop via test mode you added
    out = subprocess.run(
        ["bash", SCRIPT, "--test-wait-loop-only"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    ).stderr  # logs go to stderr in script

    # Should say attempt 1/2 then 2/2 for the grace window
    assert "attempt 1/2" in out
    assert "retry 2/2" in out or "attempt 2/2" in out
