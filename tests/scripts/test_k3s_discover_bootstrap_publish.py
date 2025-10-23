import os
import subprocess
import time
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh")


def _hostname_short() -> str:
    return subprocess.check_output(["hostname", "-s"], text=True).strip()


def test_bootstrap_publish_uses_avahi_publish(tmp_path):
    hostname = _hostname_short()
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

    systemctl = bin_dir / "systemctl"
    systemctl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    systemctl.chmod(0o755)

    browse = bin_dir / "avahi-browse"
    browse.write_text(
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "cat <<'EOF'\n"
            f"=;eth0;IPv4;k3s-sugar-dev@{hostname}.local;_k3s-sugar-dev._tcp;local;{hostname}.local;192.0.2.10;6443;"
            "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
            f"txt=leader={hostname}.local;txt=phase=bootstrap\n"
            "EOF\n"
        ),
        encoding="utf-8",
    )
    browse.chmod(0o755)

    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}:{env.get('PATH', '')}",
        "SUGARKUBE_CLUSTER": "sugar",
        "SUGARKUBE_ENV": "dev",
        "ALLOW_NON_ROOT": "1",
        "SUGARKUBE_AVAHI_SERVICE_DIR": str(tmp_path / "avahi"),
        "SUGARKUBE_TOKEN": "dummy",  # bypass token requirement
        "SUGARKUBE_MDNS_SELF_CHECK_ATTEMPTS": "1",
        "SUGARKUBE_MDNS_SELF_CHECK_DELAY": "0",
        "SUGARKUBE_DEBUG": "1",
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

    assert "-H" in log_contents
    assert f"k3s-sugar-dev@{hostname}.local" in log_contents
    assert "_k3s-sugar-dev._tcp" in log_contents
    assert "k3s=1" in log_contents
    assert "cluster=sugar" in log_contents
    assert "env=dev" in log_contents
    assert "role=bootstrap" in log_contents
    assert f"leader={hostname}.local" in log_contents
    assert "phase=bootstrap" in log_contents

    # Service file should have been cleaned up by the EXIT trap
    service_file = tmp_path / "avahi" / "k3s-sugar-dev.service"
    assert not service_file.exists()

    # stderr should mention that avahi-publish-service is advertising the bootstrap role
    assert "avahi-publish-service advertising bootstrap" in result.stderr


def test_bootstrap_publish_handles_trailing_dot_hostname(tmp_path):
    hostname = _hostname_short()
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

    systemctl = bin_dir / "systemctl"
    systemctl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    systemctl.chmod(0o755)

    browse = bin_dir / "avahi-browse"
    browse.write_text(
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "cat <<'EOF'\n"
            f"=;eth0;IPv4;k3s-sugar-dev@{hostname}.local.;_k3s-sugar-dev._tcp;local.;"
            f"{hostname}.local.;192.0.2.10;6443;"
            "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
            f"txt=leader={hostname}.local.;txt=phase=bootstrap\n"
            "EOF\n"
        ),
        encoding="utf-8",
    )
    browse.chmod(0o755)

    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}:{env.get('PATH', '')}",
        "SUGARKUBE_CLUSTER": "sugar",
        "SUGARKUBE_ENV": "dev",
        "ALLOW_NON_ROOT": "1",
        "SUGARKUBE_AVAHI_SERVICE_DIR": str(tmp_path / "avahi"),
        "SUGARKUBE_TOKEN": "dummy",
        "SUGARKUBE_MDNS_SELF_CHECK_ATTEMPTS": "1",
        "SUGARKUBE_MDNS_SELF_CHECK_DELAY": "0",
        "SUGARKUBE_DEBUG": "1",
    })

    result = subprocess.run(
        ["bash", SCRIPT, "--test-bootstrap-publish"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    log_contents = log_path.read_text(encoding="utf-8")
    assert "START:" in log_contents
    assert f"leader={hostname}.local" in log_contents

    assert "Avahi did not report bootstrap advertisement" not in result.stderr


def test_publish_binds_host_and_self_check_delays(monkeypatch, tmp_path):
    """
    Publishing with -H <FQDN> must make SRV/TXT point to that host, and
    a short delay before browsing should be sufficient for the self-check to see it.
    """

    hostname = _hostname_short()
    fqdn = f"{hostname}.local"
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

    systemctl = bin_dir / "systemctl"
    systemctl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    systemctl.chmod(0o755)

    start_file = tmp_path / "start"
    start_file.write_text(str(int(time.time())), encoding="utf-8")

    advertised_host = f"{fqdn.upper()}."

    browse = bin_dir / "avahi-browse"
    browse.write_text(
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"start=$(cat '{start_file}')\n"
            "now=$(date +%s)\n"
            "while (( now - start < 1 )); do\n"
            "  sleep 0.1\n"
            "  now=$(date +%s)\n"
            "done\n"
            "cat <<'EOF'\n"
            f"=;eth0;IPv4;k3s-sugar-dev@{advertised_host};_k3s-sugar-dev._tcp;local;{advertised_host};192.0.2.10;6443;"
            "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
            f"txt=leader={advertised_host};txt=phase=bootstrap\n"
            "EOF\n"
        ),
        encoding="utf-8",
    )
    browse.chmod(0o755)

    path_env = f"{bin_dir}:{os.environ.get('PATH', '')}"
    monkeypatch.setenv("PATH", path_env)
    monkeypatch.setenv("SUGARKUBE_CLUSTER", "sugar")
    monkeypatch.setenv("SUGARKUBE_ENV", "dev")
    monkeypatch.setenv("ALLOW_NON_ROOT", "1")
    monkeypatch.setenv("SUGARKUBE_AVAHI_SERVICE_DIR", str(tmp_path / "avahi"))
    monkeypatch.setenv("SUGARKUBE_TOKEN", "dummy")
    monkeypatch.setenv("SUGARKUBE_MDNS_SELF_CHECK_ATTEMPTS", "1")
    monkeypatch.setenv("SUGARKUBE_MDNS_SELF_CHECK_DELAY", "0")
    monkeypatch.setenv("SUGARKUBE_DEBUG", "1")

    result = subprocess.run(
        ["bash", SCRIPT, "--test-bootstrap-publish"],
        text=True,
        capture_output=True,
        check=True,
    )

    log_contents = log_path.read_text(encoding="utf-8")
    assert "START:" in log_contents
    assert f"leader={fqdn}" in log_contents
    assert "phase=bootstrap" in log_contents

    publish_log = Path("/tmp/sugar-publish.log")
    assert publish_log.exists()

    assert "Confirmed Avahi reports bootstrap advertisement" in result.stderr
    assert fqdn in result.stderr


def test_bootstrap_publish_fails_without_mdns(tmp_path):
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

    browse = bin_dir / "avahi-browse"
    browse.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "# Emit nothing to simulate missing adverts\n",
        encoding="utf-8",
    )
    browse.chmod(0o755)

    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}:{env.get('PATH', '')}",
        "SUGARKUBE_CLUSTER": "sugar",
        "SUGARKUBE_ENV": "dev",
        "ALLOW_NON_ROOT": "1",
        "SUGARKUBE_AVAHI_SERVICE_DIR": str(tmp_path / "avahi"),
        "SUGARKUBE_TOKEN": "dummy",
        "SUGARKUBE_MDNS_SELF_CHECK_ATTEMPTS": "2",
        "SUGARKUBE_MDNS_SELF_CHECK_DELAY": "0",
        "SUGARKUBE_DEBUG": "1",
    })

    result = subprocess.run(
        ["bash", SCRIPT, "--test-bootstrap-publish"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Avahi did not report bootstrap advertisement" in result.stderr

    service_file = tmp_path / "avahi" / "k3s-sugar-dev.service"
    assert not service_file.exists()
