"""Unit tests for the multi-node join rehearsal helper."""

from __future__ import annotations

import argparse
import importlib
import pathlib
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
