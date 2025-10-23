import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "configure_k3s_node_ip.sh"


def _run_parser(sample: str, tmp_path: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["SYSTEMCTL_BIN"] = ""
    env["SUGARKUBE_LOG_DIR"] = str(tmp_path / "logs")
    return subprocess.run(
        ["bash", str(SCRIPT), "--parse-stdin"],
        input=sample,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_selects_first_ipv4_address(tmp_path: Path) -> None:
    sample = (
        "2: eth0    inet 10.0.0.5/24 brd 10.0.0.255 scope global eth0\n"
        "    valid_lft forever preferred_lft forever\n"
        "3: eth0    inet 10.0.0.6/24 brd 10.0.0.255 scope global secondary eth0\n"
        "    valid_lft forever preferred_lft forever\n"
    )

    result = _run_parser(sample, tmp_path)

    assert result.returncode == 0
    assert result.stdout.strip() == "10.0.0.5"


def test_returns_error_when_no_ipv4_found(tmp_path: Path) -> None:
    sample = "2: eth0    link/ether aa:bb:cc:dd:ee:ff brd ff:ff:ff:ff:ff:ff\n"

    result = _run_parser(sample, tmp_path)

    assert result.returncode != 0
    assert result.stdout.strip() == ""
