"""Supported YAML binding, migration, and failure-safe Ethernet configuration."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/configure_k3s_node_ip.sh"


@pytest.fixture
def setup(tmp_path):
    units = tmp_path / "systemd"
    units.mkdir()
    config = tmp_path / "config"
    ip = tmp_path / "ip"
    ip.write_text('#!/bin/sh\ncat "$IP_SAMPLE"\n')
    ip.chmod(0o755)
    sample = tmp_path / "sample"
    sample.write_text("2: eth0 inet 192.168.50.12/24 scope global eth0\n")
    systemctl = tmp_path / "systemctl"
    systemctl.write_text('#!/bin/sh\necho "$*" >> "$CALLS"\nexit 0\n')
    systemctl.chmod(0o755)
    env = {
        **os.environ,
        "IP_CMD": str(ip),
        "IP_SAMPLE": str(sample),
        "SYSTEMCTL_BIN": str(systemctl),
        "CALLS": str(tmp_path / "calls"),
        "SYSTEMD_SYSTEM_DIR": str(units),
        "SYSTEMD_UNIT_PATHS": str(units),
        "SUGARKUBE_LOG_DIR": str(tmp_path / "log"),
        "K3S_CONFIG_DIR": str(config),
        "K3S_DATA_DIR": str(tmp_path / "data"),
        "TLS_SAN_TEMPLATE_PATH": str(
            ROOT / "systemd/etc/rancher/k3s/config.yaml.d/10-sugarkube-tls.yaml"
        ),
        "SUGARKUBE_MDNS_INTERFACE": "eth0",
        "SUGARKUBE_FLANNEL_IFACE": "eth0",
    }
    return env, units, config, sample


def run(setup, *args):
    return subprocess.run(
        ["bash", str(SCRIPT), *args], env=setup[0], capture_output=True, text=True
    )


def test_supported_yaml_and_idempotent_dhcp_change(setup):
    env, units, config, sample = setup
    assert run(setup).returncode == 0
    dest = config / "config.yaml.d/20-sugarkube-network.yaml"
    assert 'node-ip: "192.168.50.12"' in dest.read_text()
    assert 'flannel-iface: "eth0"' in dest.read_text()
    original = dest.stat().st_mtime_ns
    assert run(setup).returncode == 0
    assert dest.stat().st_mtime_ns == original
    sample.write_text("2: eth0 inet 192.168.50.99/24 scope global eth0\n")
    assert run(setup).returncode == 0
    assert 'node-ip: "192.168.50.99"' in dest.read_text()
    calls = Path(env["CALLS"]).read_text()
    assert "restart" not in calls
    assert "daemon-reload" not in calls


def test_existing_server_requires_explicit_prepare_and_never_restarts(setup):
    env, units, config, _ = setup
    (units / "k3s.service").touch()
    legacy = units / "k3s.service.d/10-node-ip.conf"
    legacy.parent.mkdir()
    old = "[Service]\nEnvironment=K3S_NODE_IP=192.168.50.1\nEnvironment=K3S_FLANNEL_IFACE=eth0\n"
    legacy.write_text(old)
    assert run(setup).returncode == 2
    assert legacy.read_text() == old
    assert not (config / "config.yaml.d/20-sugarkube-network.yaml").exists()
    assert run(setup, "--prepare-server").returncode == 0
    assert not legacy.exists()
    assert Path(str(legacy) + ".pre-yaml").read_text() == old
    assert run(setup, "--prepare-server").returncode == 0
    assert not Path(env["CALLS"]).exists()


@pytest.mark.parametrize(
    "content",
    [
        "",
        "2: eth0 inet 169.254.1.2/16 scope link eth0\n",
        "2: eth0 inet 999.1.1.1/24 scope global eth0\n",
        "2: eth0 inet 10.0.0.1/24 scope global secondary eth0\n",
    ],
)
def test_missing_or_invalid_ip_preserves_configuration(setup, content):
    _, _, config, sample = setup
    assert run(setup).returncode == 0
    dest = config / "config.yaml.d/20-sugarkube-network.yaml"
    old = dest.read_bytes()
    sample.write_text(content)
    assert run(setup).returncode != 0
    assert dest.read_bytes() == old


def test_custom_legacy_dropin_preserved(setup):
    _, units, _, _ = setup
    legacy = units / "k3s-agent.service.d/10-node-ip.conf"
    legacy.parent.mkdir()
    old = "[Service]\nEnvironment=K3S_NODE_IP=10.0.0.1\nExecStart=/custom\n"
    legacy.write_text(old)
    assert run(setup).returncode == 0
    assert legacy.read_text() == old


def test_unmanaged_yaml_and_symlink_are_not_overwritten(setup):
    _, _, config, _ = setup
    dest = config / "config.yaml.d/20-sugarkube-network.yaml"
    dest.parent.mkdir(parents=True)
    dest.write_text("node-ip: 10.0.0.1\n")
    assert run(setup).returncode == 2
    assert dest.read_text() == "node-ip: 10.0.0.1\n"
    dest.unlink()
    target = config / "operator.yaml"
    target.write_text("original")
    dest.symlink_to(target)
    assert run(setup).returncode == 2
    assert target.read_text() == "original"


def test_interface_mismatch_is_rejected(setup):
    setup[0]["SUGARKUBE_FLANNEL_IFACE"] = "wlan0"
    assert run(setup).returncode == 2
    assert not (setup[2] / "config.yaml.d/20-sugarkube-network.yaml").exists()


def test_persisted_server_without_unit_is_guarded(setup):
    env, _, config, _ = setup
    data = config / "data"
    (data / "server/db").mkdir(parents=True)
    env["K3S_DATA_DIR"] = str(data)
    assert run(setup).returncode == 2
    assert not (config / "config.yaml.d/20-sugarkube-network.yaml").exists()


def test_ip_command_failure_cannot_use_partial_output(setup):
    env, _, config, _ = setup
    assert run(setup).returncode == 0
    dest = config / "config.yaml.d/20-sugarkube-network.yaml"
    before = dest.read_bytes()
    Path(env["IP_CMD"]).write_text(
        '#!/bin/sh\necho "2: eth0 inet 192.168.50.99/24 scope global eth0"\nexit 1\n'
    )
    assert run(setup).returncode == 1
    assert dest.read_bytes() == before


def test_atomic_replace_failure_preserves_old_yaml(setup):
    env, _, config, sample = setup
    assert run(setup).returncode == 0
    dest = config / "config.yaml.d/20-sugarkube-network.yaml"
    before = dest.read_bytes()
    sample.write_text("2: eth0 inet 192.168.50.99/24 scope global eth0\n")
    binaries = config / "bin"
    binaries.mkdir()
    stub = binaries / "mv"
    stub.write_text("#!/bin/sh\nexit 1\n")
    stub.chmod(0o755)
    env["PATH"] = str(binaries) + ":" + env["PATH"]
    assert run(setup).returncode == 2
    assert dest.read_bytes() == before


def test_ambiguous_primary_addresses_are_rejected(setup):
    _, _, config, sample = setup
    sample.write_text(
        "2: eth0 inet 192.168.50.12/24 scope global eth0\n"
        "2: eth0 inet 10.0.0.12/24 scope global eth0\n"
    )
    assert run(setup).returncode == 1
    assert not (config / "config.yaml.d/20-sugarkube-network.yaml").exists()


def test_concurrent_prepare_is_rejected(setup):
    import fcntl

    _, _, config, _ = setup
    config.mkdir()
    with (config / ".sugarkube-network.lock").open("w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert run(setup).returncode == 2
    assert not (config / "config.yaml.d/20-sugarkube-network.yaml").exists()


def test_initial_tls_setup_and_existing_policy_preserved(setup):
    _, _, config, _ = setup
    assert run(setup).returncode == 0
    tls = config / "config.yaml.d/10-sugarkube-tls.yaml"
    assert "tls-san:" in tls.read_text()
    tls.write_text('tls-san:\n  - "operator.local"\n')
    assert run(setup).returncode == 0
    assert tls.read_text() == 'tls-san:\n  - "operator.local"\n'


def test_retry_after_failed_replace_converges_without_restart(setup):
    env, _, config, sample = setup
    assert run(setup).returncode == 0
    sample.write_text("2: eth0 inet 192.168.50.99/24 scope global eth0\n")
    binaries = config / "bin"
    binaries.mkdir()
    stub = binaries / "mv"
    stub.write_text("#!/bin/sh\nexit 1\n")
    stub.chmod(0o755)
    env["PATH"] = str(binaries) + ":" + env["PATH"]
    assert run(setup).returncode == 2
    stub.unlink()
    assert run(setup).returncode == 0
    dest = config / "config.yaml.d/20-sugarkube-network.yaml"
    assert 'node-ip: "192.168.50.99"' in dest.read_text()
    assert "restart" not in Path(env["CALLS"]).read_text()


@pytest.mark.parametrize("server_evidence", ["unit", "database"])
def test_matching_yaml_does_not_authorize_pending_legacy_migration(setup, server_evidence):
    env, units, config, _ = setup
    assert run(setup).returncode == 0
    dest = config / "config.yaml.d/20-sugarkube-network.yaml"
    original_mtime = dest.stat().st_mtime_ns
    if server_evidence == "unit":
        (units / "k3s.service").touch()
    else:
        (Path(env["K3S_DATA_DIR"]) / "server/db").mkdir(parents=True)
    legacy = units / "k3s.service.d/10-node-ip.conf"
    legacy.parent.mkdir()
    old = "[Service]\nEnvironment=K3S_NODE_IP=192.168.50.1\n"
    legacy.write_text(old)

    # A previous attempt may have committed the YAML but not the migration.
    assert run(setup).returncode == 2
    assert legacy.read_text() == old
    assert not Path(str(legacy) + ".pre-yaml").exists()
    assert dest.stat().st_mtime_ns == original_mtime
    assert run(setup, "--prepare-server").returncode == 0
    assert Path(str(legacy) + ".pre-yaml").read_text() == old
    assert not legacy.exists()
    assert run(setup).returncode == 0  # Fully converged retry performs no migration.
    assert dest.stat().st_mtime_ns == original_mtime
    assert "restart" not in Path(env["CALLS"]).read_text()
