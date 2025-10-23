import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cleanup_mdns_publishers.sh"


def test_cleanup_mdns_publishers_terminates_processes(tmp_path):
    runtime_dir = tmp_path / "run"
    runtime_dir.mkdir()

    cluster = "sugar"
    environment = "dev"

    bootstrap_proc = subprocess.Popen(["sleep", "60"])
    server_proc = subprocess.Popen(["sleep", "60"])
    stray_proc = subprocess.Popen(
        ["bash", "-c", "exec -a 'avahi-publish-service _k3s-sugar-dev._tcp' sleep 60"]
    )

    bootstrap_pidfile = runtime_dir / f"mdns-{cluster}-{environment}-bootstrap.pid"
    server_pidfile = runtime_dir / f"mdns-{cluster}-{environment}-server.pid"
    bootstrap_pidfile.write_text(str(bootstrap_proc.pid), encoding="utf-8")
    server_pidfile.write_text(str(server_proc.pid), encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "SUGARKUBE_CLUSTER": cluster,
            "SUGARKUBE_ENV": environment,
            "SUGARKUBE_RUNTIME_DIR": str(runtime_dir),
        }
    )

    try:
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
    finally:
        for proc in (bootstrap_proc, server_proc, stray_proc):
            if proc.poll() is None:
                proc.terminate()
        for proc in (bootstrap_proc, server_proc, stray_proc):
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1)

    assert result.returncode == 0, result.stderr
    assert "killing bootstrap publisher" in result.stdout
    assert "killing server publisher" in result.stdout
    assert "pkill stray avahi-publish-service" in result.stdout
    assert "dynamic publishers terminated" in result.stdout

    assert not bootstrap_pidfile.exists()
    assert not server_pidfile.exists()
    assert bootstrap_proc.poll() is not None
    assert server_proc.poll() is not None
    assert stray_proc.poll() is not None
