import os
import subprocess
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh")


def _hostname_short() -> str:
    return subprocess.check_output(["hostname", "-s"], text=True).strip()


def test_bootstrap_publish_uses_avahi_publish(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "publish.log"

    stub = bin_dir / "avahi-publish-service"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo \"START:$*\" >> '{log_path}'\n"
        "trap 'echo TERM >> \"" + str(log_path) + "\"; exit 0' TERM INT\n"
        "while true; do sleep 1; done\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}:{env.get('PATH', '')}",
        "SUGARKUBE_CLUSTER": "sugar",
        "SUGARKUBE_ENV": "dev",
        "ALLOW_NON_ROOT": "1",
        "SUGARKUBE_AVAHI_SERVICE_DIR": str(tmp_path / "avahi"),
        "SUGARKUBE_TOKEN": "dummy",  # bypass token requirement
    })

    result = subprocess.run(
        ["bash", SCRIPT, "--test-bootstrap-publish"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    # Ensure the helper logged its launch and termination
    log_contents = log_path.read_text(encoding="utf-8")
    assert "START:" in log_contents
    assert "TERM" in log_contents

    hostname = _hostname_short()
    assert "cluster=sugar" in log_contents
    assert "env=dev" in log_contents
    assert f"leader={hostname}.local" in log_contents
    assert "role=bootstrap" in log_contents

    # Service file should have been cleaned up by the EXIT trap
    service_file = tmp_path / "avahi" / "k3s-sugar-dev.service"
    assert not service_file.exists()

    # stderr should mention that avahi-publish-service is advertising the bootstrap role
    assert "avahi-publish-service advertising bootstrap" in result.stderr


def test_bootstrap_claim_retries_failed_publisher(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    attempts_file = tmp_path / "publish-attempts"
    running_flag = tmp_path / "publisher.running"

    publish_stub = bin_dir / "avahi-publish-service"
    publish_stub.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f"attempts_file='{attempts_file}'",
                f"running_flag='{running_flag}'",
                "count=0",
                'if [ -f "$attempts_file" ]; then count=$(cat "$attempts_file"); fi',
                "count=$((count + 1))",
                'echo "$count" >"$attempts_file"',
                'if [ "$count" -lt 3 ]; then',
                "  exit 1",
                "fi",
                'echo $$ >"$running_flag"',
                'trap_cmd=\'rm -f "$running_flag"; exit 0\'',
                'trap "$trap_cmd" TERM INT',
                "while true; do sleep 1; done",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    publish_stub.chmod(0o755)

    hostname = _hostname_short()
    browse_stub = bin_dir / "avahi-browse"
    browse_stub.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f"running_flag='{running_flag}'",
                "service=${@: -1}",
                'if [ "${service}" != "_https._tcp" ]; then',
                '  echo "unexpected service: ${service}" >&2',
                "  exit 1",
                "fi",
                'if [ ! -f "$running_flag" ]; then',
                "  exit 0",
                "fi",
                "cat <<'EOF'",
                (
                    f"=;eth0;IPv4;k3s API sugar/dev on {hostname};_https._tcp;local;"
                    f"{hostname}.local;192.0.2.10;6443;txt=k3s=1;txt=cluster=sugar;"
                    "txt=env=dev;txt=role=bootstrap;"
                    f"txt=leader={hostname}.local"
                ),
                "EOF",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    browse_stub.chmod(0o755)

    systemctl_stub = bin_dir / "systemctl"
    systemctl_stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    systemctl_stub.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "ALLOW_NON_ROOT": "1",
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_AVAHI_SERVICE_DIR": str(tmp_path / "avahi"),
            "DISCOVERY_ATTEMPTS": "6",
            "DISCOVERY_WAIT_SECS": "0",
        }
    )

    result = subprocess.run(
        ["bash", SCRIPT, "--test-claim-bootstrap"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "claim-ok" in result.stdout
    assert int(attempts_file.read_text(encoding="utf-8")) >= 3
    assert not running_flag.exists()
    assert "Bootstrap publisher" in result.stderr
