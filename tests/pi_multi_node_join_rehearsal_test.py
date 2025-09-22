"""Unit tests for the multi-node join rehearsal helper."""

from __future__ import annotations

import argparse
import importlib
import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

rehearsal = importlib.import_module("scripts.pi_multi_node_join_rehearsal")


@pytest.fixture
def sample_nodes() -> list[dict[str, object]]:
    return [
        {
            "metadata": {
                "name": "sugar-control",
                "labels": {"node-role.kubernetes.io/control-plane": "true"},
            },
            "status": {
                "addresses": [
                    {"type": "InternalIP", "address": "10.0.0.10"},
                    {"type": "Hostname", "address": "sugar-control"},
                ],
                "conditions": [
                    {"type": "Ready", "status": "True"},
                ],
            },
        },
        {
            "metadata": {
                "name": "sugar-worker",
                "labels": {"node-role.kubernetes.io/worker": "true"},
            },
            "status": {
                "addresses": [
                    {"type": "InternalIP", "address": "10.0.0.20"},
                ],
                "conditions": [
                    {"type": "Ready", "status": "True"},
                ],
            },
        },
    ]


def test_pick_control_plane_address_prefers_labeled_node(sample_nodes: list[dict[str, object]]):
    assert rehearsal.pick_control_plane_address(sample_nodes, "192.0.2.1") == "10.0.0.10"


def test_pick_control_plane_address_falls_back_to_any_ip():
    nodes = [
        {
            "metadata": {"name": "sugar-worker"},
            "status": {"addresses": [{"type": "InternalIP", "address": "10.0.0.21"}]},
        }
    ]
    assert rehearsal.pick_control_plane_address(nodes, "192.0.2.2") == "10.0.0.21"


def test_pick_control_plane_address_fallback_returns_host_when_missing():
    assert rehearsal.pick_control_plane_address([], "192.0.2.3") == "192.0.2.3"


def test_summarise_node_conditions_includes_ready_and_role(sample_nodes: list[dict[str, object]]):
    summaries = rehearsal.summarise_node_conditions(sample_nodes)
    assert "sugar-control: Ready=True (control-plane)" in summaries
    assert "sugar-worker: Ready=True (worker)" in summaries


def test_redact_join_secret_masks_middle():
    assert rehearsal.redact_join_secret("abcdef123456") == "abcd…3456"
    assert rehearsal.redact_join_secret("short") == "***"


def test_format_agent_summary_success():
    agent = rehearsal.AgentStatus(
        host="pi-worker",
        payload={
            "api_reachable": True,
            "install_script_reachable": True,
            "k3s_agent_state": "inactive",
            "registration_present": False,
            "data_dir_exists": False,
        },
    )
    line = rehearsal.format_agent_summary(agent)
    assert "pi-worker" in line
    assert "api=ok" in line
    assert "get.k3s.io=ok" in line
    assert "k3s-agent=inactive" in line
    assert "registration=missing" in line


def test_format_agent_summary_error_branch():
    agent = rehearsal.AgentStatus(host="pi-worker", payload={}, error="boom")
    assert rehearsal.format_agent_summary(agent) == "[pi-worker] ERROR: boom"


def test_parse_api_host_rejects_invalid_url():
    with pytest.raises(rehearsal.RehearsalError):
        rehearsal.parse_api_host("notaurl")


def test_collect_agent_status_handles_invalid_json(monkeypatch):
    class DummyResult:
        def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
            self.stdout = stdout
            self.returncode = returncode
            self.stderr = stderr

    calls = []

    def fake_run(command: list[str]) -> DummyResult:
        calls.append(command)
        return DummyResult("not-json")

    monkeypatch.setattr(rehearsal, "run_ssh", fake_run)
    namespace = argparse.Namespace(  # type: ignore[arg-type]
        agent_user="pi",
        agent_port=22,
        identity=None,
        agent_ssh_option=[],
        connect_timeout=10,
        agent_no_sudo=True,
        api_port=6443,
        api_timeout=5,
    )
    status = rehearsal.collect_agent_status("pi-worker", namespace, "10.0.0.10")
    assert not status.success
    assert "Failed to parse" in status.error
    assert calls


def test_build_ssh_command_includes_identity_and_options():
    command = rehearsal.build_ssh_command(
        "control",
        user="pi",
        port=2222,
        identity="/tmp/id_rsa",
        options=["StrictHostKeyChecking=yes"],
        connect_timeout=7,
        remote_command="echo hi",
    )
    assert command[0] == "ssh"
    assert "-i" in command and command[command.index("-i") + 1] == "/tmp/id_rsa"
    assert "StrictHostKeyChecking=yes" in command
    assert "echo hi" == command[-1]


def test_fetch_join_secret_success(monkeypatch):
    class DummyResult:
        def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
            self.stdout = stdout
            self.returncode = returncode
            self.stderr = stderr

    def fake_run(command: list[str]) -> DummyResult:  # pragma: no cover - exercised via test
        return DummyResult("secret\n")

    monkeypatch.setattr(rehearsal, "run_ssh", fake_run)
    args = argparse.Namespace(
        server="control",
        server_user="pi",
        server_port=22,
        identity=None,
        server_ssh_option=[],
        connect_timeout=10,
        server_no_sudo=True,
        secret_path="/boot/token",
    )
    assert rehearsal.fetch_join_secret(args) == "secret"


def test_fetch_join_secret_failure(monkeypatch):
    class DummyResult:
        def __init__(self, stdout: str = "", stderr: str = "boom", returncode: int = 1):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    def fake_run(command: list[str]) -> DummyResult:
        return DummyResult()

    monkeypatch.setattr(rehearsal, "run_ssh", fake_run)
    args = argparse.Namespace(
        server="control",
        server_user="pi",
        server_port=22,
        identity=None,
        server_ssh_option=[],
        connect_timeout=10,
        server_no_sudo=False,
        secret_path="/boot/token",
    )
    with pytest.raises(rehearsal.RehearsalError):
        rehearsal.fetch_join_secret(args)


def test_fetch_node_inventory_success(monkeypatch, sample_nodes):
    class DummyResult:
        def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
            self.stdout = stdout
            self.returncode = returncode
            self.stderr = stderr

    def fake_run(command: list[str]) -> DummyResult:
        return DummyResult(json.dumps({"items": sample_nodes}))

    monkeypatch.setattr(rehearsal, "run_ssh", fake_run)
    args = argparse.Namespace(
        server="control",
        server_user="pi",
        server_port=22,
        identity=None,
        server_ssh_option=[],
        connect_timeout=10,
        server_no_sudo=True,
    )
    assert rehearsal.fetch_node_inventory(args) == sample_nodes


def test_fetch_node_inventory_invalid_payload(monkeypatch):
    class DummyResult:
        def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
            self.stdout = stdout
            self.returncode = returncode
            self.stderr = stderr

    def fake_run(command: list[str]) -> DummyResult:
        return DummyResult("{}")

    monkeypatch.setattr(rehearsal, "run_ssh", fake_run)
    args = argparse.Namespace(
        server="control",
        server_user="pi",
        server_port=22,
        identity=None,
        server_ssh_option=[],
        connect_timeout=10,
        server_no_sudo=True,
    )
    with pytest.raises(rehearsal.RehearsalError):
        rehearsal.fetch_node_inventory(args)


def test_node_is_control_plane_handles_missing_labels():
    assert not rehearsal.node_is_control_plane({"metadata": {"labels": "nope"}})


def test_extract_internal_ip_returns_none_without_matches():
    assert rehearsal.extract_internal_ip({"status": {"addresses": "nope"}}) is None


def test_summarise_node_conditions_handles_non_dict_entries():
    summaries = rehearsal.summarise_node_conditions(["not-a-dict"])
    assert summaries == []


def test_determine_api_url_uses_override(sample_nodes):
    args = argparse.Namespace(server_url="https://custom:1234", server="control", api_port=6443)
    assert rehearsal.determine_api_url(args, sample_nodes) == "https://custom:1234"


def test_parse_api_host_success():
    assert rehearsal.parse_api_host("https://example.com:6443") == "example.com"


def test_collect_server_status(monkeypatch, sample_nodes):
    monkeypatch.setattr(rehearsal, "fetch_join_secret", lambda args: "secret")
    monkeypatch.setattr(rehearsal, "fetch_node_inventory", lambda args: sample_nodes)
    args = argparse.Namespace(
        server="control",
        server_user="pi",
        server_port=22,
        identity=None,
        server_ssh_option=[],
        connect_timeout=10,
        server_no_sudo=True,
        secret_path="/boot/token",
        api_port=6443,
        server_url=None,
    )
    status = rehearsal.collect_server_status(args)
    assert status.join_secret == "secret"
    assert status.api_url.endswith(":6443")


def test_build_agent_python_contains_expected_fields():
    body = rehearsal.build_agent_python("10.0.0.10", 6443, 5)
    assert "10.0.0.10" in body
    assert "registration_present" in body
    assert "print(json.dumps(result))" in body


def test_collect_agent_status_success(monkeypatch):
    payload = {
        "api_reachable": True,
        "install_script_reachable": True,
        "k3s_agent_state": "inactive",
        "registration_present": True,
        "data_dir_exists": True,
    }

    class DummyResult:
        def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
            self.stdout = stdout
            self.returncode = returncode
            self.stderr = stderr

    recorded_commands: list[list[str]] = []

    def fake_run(command: list[str]) -> DummyResult:
        recorded_commands.append(command)
        return DummyResult(json.dumps(payload))

    monkeypatch.setattr(rehearsal, "run_ssh", fake_run)
    args = argparse.Namespace(
        agent_user="pi",
        agent_port=22,
        identity=None,
        agent_ssh_option=["StrictHostKeyChecking=no"],
        connect_timeout=10,
        agent_no_sudo=False,
        api_port=6443,
        api_timeout=5,
    )
    status = rehearsal.collect_agent_status("pi-worker", args, "10.0.0.10")
    assert status.success
    assert recorded_commands


def test_collect_agent_status_nonzero_exit(monkeypatch):
    class DummyResult:
        def __init__(self, stdout: str = "", returncode: int = 1, stderr: str = "boom"):
            self.stdout = stdout
            self.returncode = returncode
            self.stderr = stderr

    def fake_run(command: list[str]) -> DummyResult:
        return DummyResult()

    monkeypatch.setattr(rehearsal, "run_ssh", fake_run)
    args = argparse.Namespace(
        agent_user="pi",
        agent_port=22,
        identity=None,
        agent_ssh_option=[],
        connect_timeout=10,
        agent_no_sudo=True,
        api_port=6443,
        api_timeout=5,
    )
    status = rehearsal.collect_agent_status("pi-worker", args, "10.0.0.10")
    assert not status.success
    assert "SSH preflight failed" in status.error


def test_collect_agent_status_non_dict_json(monkeypatch):
    class DummyResult:
        def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
            self.stdout = stdout
            self.returncode = returncode
            self.stderr = stderr

    def fake_run(command: list[str]) -> DummyResult:
        return DummyResult("[]")

    monkeypatch.setattr(rehearsal, "run_ssh", fake_run)
    args = argparse.Namespace(
        agent_user="pi",
        agent_port=22,
        identity=None,
        agent_ssh_option=[],
        connect_timeout=10,
        agent_no_sudo=True,
        api_port=6443,
        api_timeout=5,
    )
    status = rehearsal.collect_agent_status("pi-worker", args, "10.0.0.10")
    assert not status.success
    assert "not a dict" in status.error


def test_write_join_secret(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(command: list[str], check: bool = False) -> None:
        calls.append(command)

    monkeypatch.setattr(subprocess, "run", fake_run)
    path = tmp_path / "token"
    rehearsal.write_join_secret(str(path), "secret")
    assert path.read_text(encoding="utf-8") == "secret\n"
    assert calls and calls[0][:2] == ["chmod", "600"]


def test_parse_args_round_trip(tmp_path):
    args = rehearsal.parse_args(
        [
            "control",
            "--server-user",
            "root",
            "--server-port",
            "2200",
            "--server-ssh-option",
            "LogLevel=QUIET",
            "--server-no-sudo",
            "--secret-path",
            "/boot/token",
            "--server-url",
            "https://example.com:6443",
            "--api-port",
            "7443",
            "--api-timeout",
            "8",
            "--agents",
            "worker1",
            "worker2",
            "--agent-user",
            "root",
            "--agent-port",
            "2222",
            "--agent-ssh-option",
            "Compression=yes",
            "--agent-no-sudo",
            "--identity",
            str(tmp_path / "id"),
            "--connect-timeout",
            "12",
            "--json",
            "--reveal-secret",
            "--save-secret",
            str(tmp_path / "out"),
        ]
    )
    assert args.server == "control"
    assert args.server_user == "root"
    assert args.agents == ["worker1", "worker2"]
    assert args.agent_no_sudo is True
    assert args.json is True


def test_main_success(monkeypatch, capsys, sample_nodes, tmp_path):
    def fake_collect_server_status(args: argparse.Namespace) -> rehearsal.ServerStatus:
        return rehearsal.ServerStatus(
            host=args.server,
            join_secret="secret",
            api_url="https://10.0.0.10:6443",
            nodes=sample_nodes,
        )

    def fake_collect_agent_status(
        host: str,
        args: argparse.Namespace,
        api_host: str,
    ) -> rehearsal.AgentStatus:
        return rehearsal.AgentStatus(host=host, payload={"api_reachable": True})

    saved: list[tuple[str, str]] = []

    def fake_write(path: str, join_secret: str) -> None:
        saved.append((path, join_secret))

    monkeypatch.setattr(rehearsal, "collect_server_status", fake_collect_server_status)
    monkeypatch.setattr(rehearsal, "collect_agent_status", fake_collect_agent_status)
    monkeypatch.setattr(rehearsal, "write_join_secret", fake_write)
    exit_code = rehearsal.main(
        [
            "control",
            "--agents",
            "worker1",
            "--json",
            "--save-secret",
            str(tmp_path / "secret"),
            "--reveal-secret",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Saved join secret" in captured.out
    assert saved


def test_main_returns_warning_exit(monkeypatch, capsys, sample_nodes):
    def fake_collect_server_status(args: argparse.Namespace) -> rehearsal.ServerStatus:
        return rehearsal.ServerStatus(
            host=args.server,
            join_secret="secret",
            api_url="https://10.0.0.10:6443",
            nodes=sample_nodes,
        )

    def fake_collect_agent_status(
        host: str,
        args: argparse.Namespace,
        api_host: str,
    ) -> rehearsal.AgentStatus:
        return rehearsal.AgentStatus(host=host, payload={}, error="unreachable")

    monkeypatch.setattr(rehearsal, "collect_server_status", fake_collect_server_status)
    monkeypatch.setattr(rehearsal, "collect_agent_status", fake_collect_agent_status)
    exit_code = rehearsal.main(["control", "--agents", "worker1"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Run again with --reveal-secret" in captured.out
