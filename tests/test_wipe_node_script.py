import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "wipe_node.sh"


def _make_stub(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_dry_run_announces_targets(tmp_path):
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    _make_stub(fakebin / "sudo", "#!/usr/bin/env bash\nexit 0\n")
    _make_stub(fakebin / "systemctl", "#!/usr/bin/env bash\nexit 0\n")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fakebin}:{env.get('PATH', '')}",
            "DRY_RUN": "1",
            "ALLOW_NON_ROOT": "1",
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    output = result.stdout
    assert "Selected cluster=sugar env=dev" in output
    assert "k3s-killall.sh" in output
    assert "/etc/avahi/services/k3s-sugar-dev.service" in output
    assert "Summary:" in output


def test_stubbed_uninstallers_receive_calls(tmp_path):
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    log_file = tmp_path / "calls.log"
    log_path = str(log_file)

    _make_stub(fakebin / "sudo", "#!/usr/bin/env bash\nexit 1\n")
    _make_stub(
        fakebin / "rm",
        f"""#!/usr/bin/env bash
echo rm \"$@\" >> \"{log_path}\"
exit 0
""",
    )
    _make_stub(fakebin / "systemctl", "#!/usr/bin/env bash\nexit 0\n")

    for name in ("k3s-uninstall.sh", "k3s-killall.sh", "k3s-agent-uninstall.sh"):
        _make_stub(
            fakebin / name,
            f"""#!/usr/bin/env bash
echo {name} >> \"{log_path}\"
exit 0
""",
        )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fakebin}:{env.get('PATH', '')}",
            "DRY_RUN": "1",
            "ALLOW_NON_ROOT": "1",
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    log_contents = log_file.read_text(encoding="utf-8")
    for name in ("k3s-killall.sh", "k3s-uninstall.sh", "k3s-agent-uninstall.sh"):
        assert name in log_contents
