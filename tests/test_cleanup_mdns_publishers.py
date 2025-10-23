import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cleanup_mdns_publishers.sh"


def test_cleanup_mdns_publishers_terminates_processes(tmp_path):
    runtime_dir = tmp_path / "run"
    runtime_dir.mkdir()

    bootstrap_proc = subprocess.Popen(["sleep", "60"])
    server_proc = subprocess.Popen(["sleep", "60"])

    (runtime_dir / "mdns-sugar-dev-bootstrap.pid").write_text(
        str(bootstrap_proc.pid),
        encoding="utf-8",
    )
    (runtime_dir / "mdns-sugar-dev-server.pid").write_text(
        str(server_proc.pid),
        encoding="utf-8",
    )

    stray_stub = tmp_path / "avahi_stub.sh"
    stray_stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "svc=$1\n"
        "exec -a \"avahi-publish-service ${svc}\" sleep 60\n",
        encoding="utf-8",
    )
    stray_stub.chmod(0o755)
    stray_proc = subprocess.Popen([str(stray_stub), "_k3s-sugar-dev._tcp"])

    env = os.environ.copy()
    env.update(
        {
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_RUNTIME_DIR": str(runtime_dir),
            "PATH": env.get("PATH", ""),
        }
    )

    try:
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        for proc in (bootstrap_proc, server_proc, stray_proc):
            proc.wait(timeout=5)
    finally:
        for proc in (bootstrap_proc, server_proc, stray_proc):
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    assert result.returncode == 0, result.stderr
    assert "dynamic publishers terminated" in result.stdout

    assert not (runtime_dir / "mdns-sugar-dev-bootstrap.pid").exists()
    assert not (runtime_dir / "mdns-sugar-dev-server.pid").exists()
