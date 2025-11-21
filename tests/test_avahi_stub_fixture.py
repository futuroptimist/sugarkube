"""Ensure the Avahi stub fixture can publish and browse services."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "avahi_stub"


def _base_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "AVAHI_STUB_DIR": str(tmp_path / "avahi_stub"),
            "AVAHI_STUB_HOST": "node0.local",
            "AVAHI_STUB_IPV4": "10.0.0.50",
            "PATH": f"{FIXTURE_DIR}:{env['PATH']}",
        }
    )
    return env


def test_stub_roundtrip_publishes_and_browses(tmp_path: Path) -> None:
    env = _base_env(tmp_path)

    # Start the stub publisher in the background to mimic avahi-publish's lifecycle.
    publish = subprocess.Popen(
        [
            "avahi-publish",
            "-s",
            "k3s-test@node0.local",
            "_k3s-test._tcp",
            "443",
            "role=server",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Wait for the stub publisher to create the service file (max 2s).
        service_file = Path(env["AVAHI_STUB_DIR"]) / "services" / "k3s-test@node0.local.service"
        timeout = 2.0
        interval = 0.05
        start = time.time()
        while not service_file.exists():
            if time.time() - start > timeout:
                raise RuntimeError(f"Stub service file {service_file} not created after {timeout}s")
            time.sleep(interval)
        
        browse = subprocess.run(
            ["avahi-browse", "--parsable", "--terminate", "_k3s-test._tcp"],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        assert "=;" in browse.stdout
        assert "k3s-test@node0.local" in browse.stdout
        assert "10.0.0.50" in browse.stdout

        resolve = subprocess.run(
            ["avahi-resolve", "-n", "node0.local"],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        assert "node0.local" in resolve.stdout
        assert "10.0.0.50" in resolve.stdout
    finally:
        publish.terminate()
        try:
            publish.wait(timeout=2)
        except subprocess.TimeoutExpired:
            publish.kill()
