"""Supported YAML binding, migration, and failure-safe Ethernet configuration."""

import os
import shlex
import shutil
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


def inject_network_replace_failure(setup):
    import sys

    env, _, config, _ = setup
    binaries = config / "bin"
    binaries.mkdir()
    stub = binaries / "python3"
    stub.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "if len(sys.argv) > 3 and sys.argv[2] == 'publish' "
        "and sys.argv[3].endswith('/20-sugarkube-network.yaml'):\n"
        "    def fail(*args):\n"
        "        raise OSError('injected atomic replace failure')\n"
        "    os.replace = fail\n"
        "    sys.argv = sys.argv[1:]\n"
        "    exec(sys.stdin.read(), {'__name__': '__main__'})\n"
        "else:\n"
        f"    os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])\n"
    )
    stub.chmod(0o755)
    env["PATH"] = str(binaries) + ":" + env["PATH"]
    return stub


def install_file_action(monkeypatch, action, target, temporary=None):
    """Execute the actual embedded installer with real temporary filesystem paths."""
    import sys

    code = SCRIPT.read_text().split("<<'PYINSTALL'\n", 1)[1].split("\nPYINSTALL", 1)[0]
    arguments = ["-", action, str(target)]
    if temporary is not None:
        arguments.append(str(temporary))
    monkeypatch.setattr(sys, "argv", arguments)
    exec(code, {})


def test_runtime_file_and_directories_are_durable_before_hook_publication(tmp_path, monkeypatch):
    events = []
    original_sync, original_replace = os.fsync, os.replace

    def sync(fd):
        events.append(("sync", Path(os.readlink(f"/proc/self/fd/{fd}"))))
        original_sync(fd)

    def replace(source, destination):
        events.append(("replace", destination))
        original_replace(source, destination)

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(os, "replace", replace)
    runtime = tmp_path / "config" / "runtime.sh"
    hook = tmp_path / "systemd" / "k3s.service.d" / "network.conf"
    for target in (runtime, hook):
        install_file_action(monkeypatch, "prepare", target)
        staged = target.with_suffix(".tmp")
        staged.write_text("synthetic prerequisite\n")
        staged.chmod(0o644)
        install_file_action(monkeypatch, "publish", target, staged)
        publish = events.index(("replace", target))
        assert ("sync", staged) in events[:publish]
        assert events[publish + 1] == ("sync", target.parent)
    runtime_publish = events.index(("replace", runtime))
    hook_publish = events.index(("replace", hook))
    assert runtime_publish < hook_publish
    assert ("sync", runtime.parent) in events[runtime_publish:hook_publish]
    assert ("sync", tmp_path) in events[:hook_publish]


@pytest.mark.parametrize("failure", ["file", "directory"])
def test_prestart_sync_failure_never_publishes_file(tmp_path, monkeypatch, failure):
    target, staged = tmp_path / "runtime.sh", tmp_path / "staged"
    staged.write_text("synthetic prerequisite\n")
    original_sync = os.fsync

    def sync(fd):
        path = Path(os.readlink(f"/proc/self/fd/{fd}"))
        if path == (staged if failure == "file" else tmp_path):
            raise OSError("injected persistence failure")
        original_sync(fd)

    monkeypatch.setattr(os, "fsync", sync)
    with pytest.raises(OSError, match="persistence failure"):
        install_file_action(monkeypatch, "publish", target, staged)
    assert not target.exists()
    assert staged.read_text() == "synthetic prerequisite\n"


@pytest.mark.parametrize(
    "failure",
    ["directory_mode", "directory_owner", "directory_sticky", "file_mode", "file_owner", "symlink"],
)
def test_root_installation_refuses_untrusted_paths(tmp_path, monkeypatch, failure):
    import stat

    directory = tmp_path / "config"
    directory.mkdir()
    target = directory / "runtime.sh"
    target.write_text("existing content\n")
    if failure == "symlink":
        target.unlink()
        target.symlink_to(tmp_path / "absent")
    original_stat = Path.lstat

    def root_stat(path, *args, **kwargs):
        info = list(original_stat(path, *args, **kwargs))
        info[4] = 0  # Synthetic root-owned layout; no privileged filesystem access.
        if stat.S_ISDIR(info[0]):
            info[0] &= ~0o022
        bad = directory if failure.startswith("directory") else target
        if path == bad and failure.endswith("owner"):
            info[4] = 1000
        if path == bad and failure.endswith(("mode", "sticky")):
            info[0] |= 0o022
            if failure.endswith("sticky"):
                info[0] |= stat.S_ISVTX
        return os.stat_result(info)

    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(Path, "lstat", root_stat)
    with pytest.raises(SystemExit, match="[Uu]ntrusted|installing user"):
        install_file_action(monkeypatch, "prepare", target)
    if failure != "symlink":
        assert target.read_text() == "existing content\n"


@pytest.mark.parametrize(
    "failure", ["config_mode", "config_symlink", "lock_symlink", "log_symlink"]
)
def test_unsafe_paths_are_rejected_before_lock_or_log_writes(setup, tmp_path, failure):
    env, _, config, _ = setup
    victim = tmp_path / "preserve"
    victim.write_text("must remain unchanged\n")
    if failure == "config_symlink":
        other = tmp_path / "other"
        other.mkdir()
        config.symlink_to(other, target_is_directory=True)
    else:
        config.mkdir()
    if failure == "config_mode":
        config.chmod(0o777)
    if failure in ("config_mode", "config_symlink", "lock_symlink"):
        (config / ".sugarkube-network.lock").symlink_to(victim)
    else:
        log = Path(env["SUGARKUBE_LOG_DIR"]) / "configure_k3s_node_ip.log"
        log.parent.mkdir()
        log.symlink_to(victim)
    assert run(setup).returncode != 0
    assert victim.read_text() == "must remain unchanged\n"


def test_root_fixture_uses_trusted_ancestry_without_weakening_runtime(
    setup, trusted_network_test_ancestry
):
    setup[0]["PYTHONPATH"] = trusted_network_test_ancestry(synthetic_root=True)
    probe = subprocess.run(
        [
            "python3",
            "-c",
            "import os; from pathlib import Path; "
            "assert os.geteuid() == 0; assert Path('/tmp').lstat().st_mode & 0o022 == 0",
        ],
        env=setup[0],
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stderr
    assert run(setup).returncode == 0
    setup[3].write_text("2: eth0 inet 192.168.50.99/24 scope global eth0\n")
    result, loaded = boot_installed_unit(setup, "k3s.service")
    assert result.returncode == 0 and 'node-ip: "192.168.50.99"' in loaded


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
    legacy.parent.mkdir(exist_ok=True)
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
    legacy.parent.mkdir(exist_ok=True)
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
    inject_network_replace_failure(setup)
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
    stub = inject_network_replace_failure(setup)
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
    legacy.parent.mkdir(exist_ok=True)
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


def boot_installed_unit(setup, unit):
    """Offline systemd start harness: execute installed pre-starts before ExecStart.

    Uses the files persisted by preparation, with no just/helper invocation on reboot.
    Actual systemd/K3s qualification remains an owner-run staging gate.
    """
    env, units, config, _ = setup
    dropin = units / f"{unit}.d/20-sugarkube-network.conf"
    content = dropin.read_text()
    assert "After=network-online.target" in content
    commands = [
        line.split("=", 1)[1] for line in content.splitlines() if line.startswith("ExecStartPre=")
    ]
    assert len(commands) == 1
    assert str(config / "sugarkube-network-prestart.sh") in commands[0]
    assert str(SCRIPT) not in commands[0]
    for command in commands:
        result = subprocess.run(shlex.split(command), env=env, capture_output=True, text=True)
        if result.returncode:
            return result, None  # systemd must not reach ExecStart after pre-start failure.
    # Stand-in for K3s reading its configuration at process startup.
    return result, (config / "config.yaml.d/20-sugarkube-network.yaml").read_text()


@pytest.mark.parametrize("unit", ["k3s.service", "k3s-agent.service"])
def test_ordinary_reboot_refreshes_dhcp_without_manual_preparation(setup, unit):
    env, units, config, sample = setup
    assert run(setup).returncode == 0
    (units / unit).touch()
    database = Path(env["K3S_DATA_DIR"]) / "server/db/member"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"persisted-identity-and-data")
    first, loaded = boot_installed_unit(setup, unit)
    assert first.returncode == 0 and 'node-ip: "192.168.50.12"' in loaded
    sample.write_text("2: eth0 inet 192.168.50.99/24 scope global eth0\n")
    # A normal reboot runs only the installed unit, not just up or configure.
    second, loaded = boot_installed_unit(setup, unit)
    assert second.returncode == 0 and 'node-ip: "192.168.50.99"' in loaded
    assert "192.168.50.12" not in loaded
    dest = config / "config.yaml.d/20-sugarkube-network.yaml"
    mtime = dest.stat().st_mtime_ns
    assert boot_installed_unit(setup, unit)[0].returncode == 0
    assert dest.stat().st_mtime_ns == mtime
    assert database.read_bytes() == b"persisted-identity-and-data"
    assert "restart" not in Path(env["CALLS"]).read_text()


@pytest.mark.parametrize("bad_address", ["", "2: eth0 inet 169.254.1.2/16 scope global eth0\n"])
def test_boot_failure_blocks_k3s_and_preserves_previous_config(setup, bad_address):
    _, units, config, sample = setup
    assert run(setup).returncode == 0
    (units / "k3s.service").touch()
    dest = config / "config.yaml.d/20-sugarkube-network.yaml"
    old = dest.read_bytes()
    sample.write_text(bad_address)
    result, started = boot_installed_unit(setup, "k3s.service")
    assert result.returncode != 0
    assert started is None
    assert dest.read_bytes() == old


def test_installed_hook_recreates_absent_owned_yaml_from_current_address(setup):
    assert run(setup).returncode == 0
    (setup[2] / "config.yaml.d/20-sugarkube-network.yaml").unlink()
    setup[3].write_text("2: eth0 inet 192.168.50.99/24 scope global eth0\n")
    result, loaded = boot_installed_unit(setup, "k3s.service")
    assert result.returncode == 0 and 'node-ip: "192.168.50.99"' in loaded


@pytest.mark.parametrize("replacement", ["unmanaged", "symlink", "directory"])
def test_boot_refuses_unmanaged_network_path(setup, replacement):
    assert run(setup).returncode == 0
    dest = setup[2] / "config.yaml.d/20-sugarkube-network.yaml"
    dest.unlink()
    if replacement == "unmanaged":
        dest.write_text("node-ip: 192.168.50.1\n")
    elif replacement == "symlink":
        dest.symlink_to(setup[3])
    else:
        dest.mkdir()
    result, started = boot_installed_unit(setup, "k3s.service")
    assert result.returncode == 2 and started is None


def test_failed_first_server_preparation_leaves_bootstrap_capable_hook(setup):
    env, units, config, sample = setup
    (units / "k3s.service").touch()
    conflicting = units / "k3s-agent.service.d/20-sugarkube-network.conf"
    conflicting.parent.mkdir()
    conflicting.write_text("operator-owned\n")
    database = Path(env["K3S_DATA_DIR"]) / "server/db/member"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"persisted-identity-and-data")
    assert run(setup, "--prepare-server").returncode == 2
    assert (units / "k3s.service.d/20-sugarkube-network.conf").exists()
    assert not (config / "config.yaml.d/20-sugarkube-network.yaml").exists()
    # A reboot after the interrupted/failed preparation uses only persisted files.
    sample.write_text("2: eth0 inet 192.168.50.99/24 scope global eth0\n")
    result, loaded = boot_installed_unit(setup, "k3s.service")
    assert result.returncode == 0 and 'node-ip: "192.168.50.99"' in loaded
    assert conflicting.read_text() == "operator-owned\n"
    assert database.read_bytes() == b"persisted-identity-and-data"


def test_preparation_creates_non_writable_directories_under_permissive_umask(setup):
    result = subprocess.run(
        ["bash", "-c", 'umask 000; exec bash "$1"', "_", str(SCRIPT)],
        env=setup[0],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    for directory in (setup[2], setup[2] / "config.yaml.d", setup[1] / "k3s.service.d"):
        assert directory.stat().st_mode & 0o022 == 0


@pytest.mark.parametrize(
    "failure", ["missing_address", "server_guard", "hook_write", "second_hook_write"]
)
def test_just_up_preparation_failure_prevents_installation(
    setup, tmp_path, failure, ensure_just_available
):
    env, units, config, sample = setup
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(ROOT / "justfile", project / "justfile")
    shutil.copyfile(SCRIPT, scripts / SCRIPT.name)
    summary = scripts / "lib/summary.sh"
    summary.parent.mkdir()
    shutil.copyfile(ROOT / "scripts/lib/summary.sh", summary)
    for name in ("install_deps.sh", "check_memory_cgroup.sh"):
        (scripts / name).write_text("#!/bin/sh\nexit 0\n")
        (scripts / name).chmod(0o755)
    sentinel = project / "installation-reached"
    (scripts / "k3s-discover.sh").write_text(f"#!/bin/sh\ntouch '{sentinel}'\n")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "sudo").write_text('#!/bin/sh\n[ "$1" != -E ] || shift\nexec "$@"\n')
    (binaries / "sudo").chmod(0o755)
    env.update(
        {
            "PATH": f"{binaries}:{env['PATH']}",
            "SUGARKUBE_CONFIGURE_AVAHI": "0",
            "SUGARKUBE_DISABLE_WLAN_DURING_BOOTSTRAP": "0",
            "SUGARKUBE_SET_K3S_NODE_IP": "1",
            "SUGARKUBE_SUMMARY_LIB": str(summary),
        }
    )
    if failure == "missing_address":
        sample.write_text("")
    elif failure == "server_guard":
        (units / "k3s.service").touch()
    elif failure == "second_hook_write":
        conflicting = units / "k3s-agent.service.d/20-sugarkube-network.conf"
        conflicting.parent.mkdir()
        conflicting.write_text("operator-owned\n")
    else:
        config.mkdir()
        (config / "sugarkube-network-prestart.sh").write_text("operator-owned")
    result = subprocess.run(
        ["just", "up", "dev"], cwd=project, env=env, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "K3s installation blocked" in result.stderr
    assert not sentinel.exists()
    assert not (config / "config.yaml.d/20-sugarkube-network.yaml").exists()


def default_log_directory(env):
    clean = {key: value for key, value in env.items() if key != "SUGARKUBE_LOG_DIR"}
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; printf "%s" "$LOG_DIR"', "bash", str(SCRIPT)],
        env=clean,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_application_log_path_avoids_ubuntu_var_log_and_survives_boot(
    setup, tmp_path, trusted_network_test_ancestry
):
    env, units, config, sample = setup
    env["PYTHONPATH"] = trusted_network_test_ancestry(synthetic_root=True)
    default = default_log_directory(env)
    assert default == "/var/lib/sugarkube/logs"
    # Map the selected absolute default into the synthetic root filesystem.
    app_logs = tmp_path / default.lstrip("/")
    var_log = tmp_path / "var/log"
    var_log.mkdir(parents=True)
    var_log.chmod(0o775)
    legacy = var_log / "sugarkube/configure_k3s_node_ip.log"
    legacy.parent.mkdir()
    legacy.write_text("retained legacy log\n")
    env["SUGARKUBE_LOG_DIR"] = str(app_logs)
    assert run(setup).returncode == 0
    for unit in ("k3s.service", "k3s-agent.service"):
        hook = units / f"{unit}.d/20-sugarkube-network.conf"
        assert str(app_logs) in hook.read_text()
    sample.write_text("2: eth0 inet 192.168.50.99/24 scope global eth0\n")
    result, loaded = boot_installed_unit(setup, "k3s.service")
    assert result.returncode == 0, result.stderr
    assert 'node-ip: "192.168.50.99"' in loaded
    assert "Ethernet address refreshed" in (app_logs / "configure_k3s_node_ip.log").read_text()
    assert legacy.read_text() == "retained legacy log\n"
    assert var_log.stat().st_mode & 0o777 == 0o775
    assert not (Path(env["K3S_DATA_DIR"]) / "server/db").exists()
    assert "restart" not in Path(env["CALLS"]).read_text()


def test_explicit_group_writable_log_ancestor_still_rejected(
    setup, tmp_path, trusted_network_test_ancestry
):
    env, _, _, _ = setup
    env["PYTHONPATH"] = trusted_network_test_ancestry(synthetic_root=True)
    var_log = tmp_path / "var/log"
    var_log.mkdir(parents=True)
    var_log.chmod(0o775)
    env["SUGARKUBE_LOG_DIR"] = str(var_log / "sugarkube")
    result = run(setup)
    assert result.returncode != 0
    assert "Untrusted pre-start installation ownership or permissions" in result.stderr
    assert var_log.stat().st_mode & 0o777 == 0o775
    assert not (var_log / "sugarkube").exists()


def test_existing_managed_hook_log_path_change_requires_prepare_server(setup, tmp_path):
    env, units, config, _ = setup
    old_logs = Path(env["SUGARKUBE_LOG_DIR"])
    assert run(setup).returncode == 0
    old_content = (old_logs / "configure_k3s_node_ip.log").read_bytes()
    (units / "k3s.service").touch()
    hook = units / "k3s.service.d/20-sugarkube-network.conf"
    old_hook = hook.read_bytes()
    database = Path(env["K3S_DATA_DIR"]) / "server/db/member"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"original-database")
    new_logs = tmp_path / "var/lib/sugarkube/logs"
    env["SUGARKUBE_LOG_DIR"] = str(new_logs)
    assert run(setup).returncode == 2
    assert hook.read_bytes() == old_hook
    assert run(setup, "--prepare-server").returncode == 0
    assert str(new_logs) in hook.read_text()
    assert (old_logs / "configure_k3s_node_ip.log").read_bytes() == old_content
    assert database.read_bytes() == b"original-database"
    assert "daemon-reload" not in Path(env["CALLS"]).read_text()
    assert "restart" not in Path(env["CALLS"]).read_text()
