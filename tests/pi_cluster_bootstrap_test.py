from __future__ import annotations

import sys
from pathlib import Path

from scripts import pi_cluster_bootstrap as bootstrap


def test_render_cloud_init_injects_hostname_and_wifi() -> None:
    base = "#cloud-config\npackage_update: true\n"
    defaults = bootstrap.NodeDefaults(
        ssh_authorized_keys=["ssh-ed25519 AAAA... test"],
        wifi=bootstrap.WifiConfig(ssid="TestNet", psk="secret"),
    )
    node = bootstrap.NodeConfig(
        device="/dev/sda",
        hostname="sugar-control",
        report_dir=Path("/tmp/reports"),
    )

    rendered = bootstrap.render_cloud_init(base, node, defaults)

    assert "hostname: sugar-control" in rendered
    assert "ssh_authorized_keys:" in rendered
    assert "TestNet" in rendered
    assert rendered.startswith("#cloud-config\n")


def test_build_flash_command_includes_sudo_and_overrides(tmp_path: Path) -> None:
    node = bootstrap.NodeConfig(
        device="/dev/sdb",
        name="worker",
        report_dir=tmp_path / "reports",
    )
    cloud_init = tmp_path / "worker-user-data.yaml"
    command = bootstrap.build_flash_command(
        node,
        Path("/images/sugarkube.img"),
        cloud_init=cloud_init,
    )

    assert command[0] == "sudo"
    assert command[1] == sys.executable
    assert "--cloud-init" in command
    assert str(cloud_init) in command


def test_build_join_command_round_trips_arguments(tmp_path: Path) -> None:
    identity = tmp_path / "id_ed25519"
    identity.write_text("dummy")
    join = bootstrap.JoinConfig(
        server="control.local",
        agents=["worker-a.local", "worker-b.local"],
        agent_user="pi",
        identity=identity,
        apply_wait_timeout=600,
        api_port=6443,
        extra_args=["--connect-timeout", "15"],
    )

    command = bootstrap.build_join_command(join)

    assert "--agents" in command
    assert "--apply-wait-timeout" in command
    assert str(identity) in command
    assert command.count("--connect-timeout") == 1


def test_load_cluster_config_resolves_relative_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "cluster.toml"
    config_path.write_text(
        """
[image]
dir = "./images"
name = "custom.img"

[defaults]
use_sudo = false
report_root = "./reports"
ssh_authorized_keys = ["ssh-ed25519 AAAA... test"]

[[nodes]]
device = "/dev/sda"
hostname = "control"
report_dir = "./reports/control"

[[nodes]]
device = "/dev/sdb"
hostname = "worker"

[cluster.join]
server = "control.local"
agents = ["worker.local"]
identity = "./id_ed25519"
apply_wait_timeout = 420
"""
    )
    (tmp_path / "images").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "control").mkdir()
    (tmp_path / "id_ed25519").write_text("dummy")

    config = bootstrap.load_cluster_config(config_path)

    assert config.image_dir == (tmp_path / "images").resolve()
    assert config.image_name == "custom.img"
    assert config.nodes[0].report_dir == (tmp_path / "reports" / "control").resolve()
    assert config.nodes[1].report_dir == (tmp_path / "reports" / "worker").resolve()
    assert config.join is not None
    assert config.join.apply_wait_timeout == 420
    assert config.join.identity == (tmp_path / "id_ed25519").resolve()


def test_load_cluster_config_enables_workflow_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "cluster.toml"
    config_path.write_text(
        """
[image]
download_args = []
[image.workflow]
trigger = true
clone_token_place = true

[[nodes]]
device = "/dev/sdz"
hostname = "controller"
"""
    )

    config = bootstrap.load_cluster_config(config_path)

    assert "--mode" in config.download_args
    assert "workflow" in config.download_args
    assert config.workflow is not None
    assert config.workflow.clone_token_place is True


def test_build_workflow_dispatch_command_sets_inputs() -> None:
    workflow = bootstrap.WorkflowConfig(
        trigger=True,
        ref="main",
        clone_sugarkube=True,
        clone_token_place=False,
        clone_dspace=True,
    )

    command = bootstrap.build_workflow_dispatch_command(workflow)

    assert command[:4] == ["gh", "workflow", "run", "pi-image.yml"]
    assert "--field" in command
    assert any("clone_sugarkube=true" in part for part in command)
    assert any("clone_token_place=false" in part for part in command)
