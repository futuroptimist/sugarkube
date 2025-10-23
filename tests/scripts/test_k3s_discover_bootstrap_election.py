import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"


def _make_env(tmp_path: Path) -> dict:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    sudo = bin_dir / "sudo"
    sudo.write_text("#!/usr/bin/env bash\nexec \"$@\"\n", encoding="utf-8")
    sudo.chmod(0o755)

    systemctl = bin_dir / "systemctl"
    systemctl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    systemctl.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_AVAHI_SERVICE_DIR": str(tmp_path / "avahi"),
            "DISCOVERY_WAIT_SECS": "0",
            "DISCOVERY_ATTEMPTS": "5",
            "SUGARKUBE_TOKEN": "dummy",
        }
    )
    return env


def test_claim_leadership_aborts_when_server_advertised(tmp_path):
    env = _make_env(tmp_path)

    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")

    server = tmp_path / "server.txt"
    server.write_text(
        "=;eth0;IPv4;k3s API sugar/dev on host0;_https._tcp;local;host0.local;192.168.1.10;6443;"
        "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server\n",
        encoding="utf-8",
    )

    env["SUGARKUBE_MDNS_FIXTURE_SEQUENCE"] = f"{empty}:{server}"

    result = subprocess.run(
        ["bash", str(SCRIPT), "--test-claim-leadership"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "deferring cluster initialization" in result.stderr
