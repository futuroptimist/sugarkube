"""Offline recovery planning must never turn ambiguous discovery into authority."""

import copy
import importlib.util
import json
import runpy
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ethernet_recovery_plan.py"
SPEC = importlib.util.spec_from_file_location("ethernet_recovery_plan", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
NOW = datetime(2026, 10, 15, 6, tzinfo=timezone.utc)


@pytest.fixture
def evidence():
    data = {
        "schema_version": 1,
        "captured_at": NOW.isoformat(),
        "cluster_id": "cluster-a",
        "members": [],
        "health": [],
        "nodes": [],
    }
    for i in range(3):
        name = f"server{i}"
        address = f"192.168.1.{10 + i}"
        member = f"{name}-persisted-suffix"
        data["members"].append(
            {
                "id": str(i + 1),
                "name": member,
                "isLearner": False,
                "peerURLs": [f"https://{address}:2380"],
            }
        )
        data["health"].append(
            {
                "member_id": str(i + 1),
                "cluster_id": "cluster-a",
                "healthy": True,
                "method": "authenticated-etcd-proposal",
            }
        )
        data["nodes"].append(
            {
                "name": name,
                "member_id": str(i + 1),
                "mdns_name": name + ".local",
                "mdns_ipv4": [address],
                "ethernet_ipv4": address,
                "interface": "eth0",
                "join_targets": ["https://server0.local:6443"] if i else [],
                "object": {
                    "metadata": {
                        "name": name,
                        "uid": f"uid-{i}",
                        "resourceVersion": "123",
                        "annotations": {
                            "etcd.k3s.cattle.io/node-name": member,
                            "k3s.io/internal-ip": address,
                        },
                    },
                    "status": {
                        "addresses": [
                            {"type": "InternalIP", "address": address},
                            {"type": "Hostname", "address": name},
                        ]
                    },
                },
            }
        )
    return data


def test_no_change_idempotent_and_does_not_mutate_evidence(evidence):
    before = copy.deepcopy(evidence)
    first = MODULE.plan(evidence, NOW)
    assert first == MODULE.plan(evidence, NOW)
    assert first["mode"] == "no-change"
    assert first["automatic_actions"] == []
    assert evidence == before


def changed(evidence):
    node = evidence["nodes"][2]
    node["ethernet_ipv4"] = "192.168.1.99"
    node["mdns_ipv4"] = ["192.168.1.99"]
    node["object"]["metadata"]["annotations"]["k3s.io/internal-ip"] = "192.168.1.99"
    node["join_targets"] = ["https://192.168.1.10:6443"]
    evidence["health"][2]["healthy"] = False
    return node


def test_changed_address_live_quorum_and_guarded_status_only_patch(evidence):
    node = changed(evidence)
    result = MODULE.plan(evidence, NOW)
    assert result["mode"] == "live-quorum-review"
    candidate = result["candidates"][0]
    assert candidate["membership_review"]["member_id"] == "3"
    assert candidate["membership_review"]["candidate_peer_urls"] == ["https://192.168.1.99:2380"]
    assert candidate["join_target_review"] == ["https://192.168.1.10:6443"]
    patch = candidate["status_patch_review"]
    assert patch["subresource"] == "status"
    assert [p["op"] for p in patch["patch"]] == ["test", "test", "test", "replace"]
    assert patch["patch"][0]["value"] == node["object"]["metadata"]["uid"]
    assert patch["patch"][-1]["path"] == "/status/addresses"
    assert patch["patch"][-1]["value"][1] == {"type": "Hostname", "address": "server2"}
    assert result["automatic_actions"] == []


@pytest.mark.parametrize("healthy_count", [0, 1])
def test_no_proven_quorum_produces_no_candidates(evidence, healthy_count):
    changed(evidence)
    for i, health in enumerate(evidence["health"]):
        health["healthy"] = i < healthy_count
    result = MODULE.plan(evidence, NOW)
    assert result["mode"] == "operator-intervention"
    assert result["candidates"] == []
    assert result["automatic_actions"] == []
    assert "does not prove permanent quorum loss" in result["constraints"][-1]


@pytest.mark.parametrize(
    "case",
    [
        "cluster",
        "duplicate",
        "learner",
        "unknown",
        "mdns",
        "annotation",
        "identity",
        "status",
        "wifi",
        "quorum",
        "tcp",
        "future",
        "stale",
    ],
)
def test_ambiguous_or_unsafe_evidence_fails_closed(evidence, case):
    node = changed(evidence)
    if case == "cluster":
        evidence["health"][0]["cluster_id"] = "wrong"
    elif case == "duplicate":
        evidence["members"][1]["id"] = "1"
    elif case == "learner":
        evidence["members"][1]["isLearner"] = True
    elif case == "unknown":
        evidence["health"][0]["member_id"] = "unknown"
    elif case == "mdns":
        node["mdns_ipv4"].append("192.168.1.98")
    elif case == "annotation":
        node["object"]["metadata"]["annotations"]["k3s.io/internal-ip"] = "192.168.1.12"
    elif case == "identity":
        node["object"]["metadata"]["annotations"]["etcd.k3s.cattle.io/node-name"] = "wrong"
    elif case == "status":
        node["object"]["status"]["addresses"].append({"type": "InternalIP", "address": "::1"})
    elif case == "wifi":
        node["interface"] = "wlan0"
    elif case == "quorum":
        evidence["health"][0]["healthy"] = False
        evidence["health"][2]["healthy"] = True
    elif case == "tcp":
        evidence["health"][0]["method"] = "tcp-connect"
    elif case == "future":
        evidence["captured_at"] = (NOW + timedelta(seconds=1)).isoformat()
    elif case == "stale":
        evidence["captured_at"] = (NOW - timedelta(seconds=301)).isoformat()
    with pytest.raises(MODULE.UnsafeEvidence):
        MODULE.plan(evidence, NOW)


def test_cli_malformed_evidence_has_no_actions_or_secrets(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text('{"secret":"do-not-echo"}')
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)], text=True, capture_output=True
    )
    assert result.returncode == 2
    assert "do-not-echo" not in result.stdout
    assert json.loads(result.stdout)["candidates"] == []


def test_mdns_discovery_is_bounded_and_preserves_quorum_evidence_age(evidence, monkeypatch):
    calls = []

    def resolve(argv, **kwargs):
        calls.append((argv, kwargs))
        index = int(argv[-1][6])
        return subprocess.CompletedProcess(argv, 0, f"{argv[-1]}\t192.168.1.{10 + index}\n")

    monkeypatch.setattr(MODULE.subprocess, "run", resolve)
    captured = evidence["captured_at"]
    MODULE.resolve_mdns(evidence)
    assert len(calls) == 3
    assert all(call[1]["timeout"] == 5 and call[1]["check"] for call in calls)
    assert evidence["captured_at"] == captured
    assert MODULE.plan(evidence, NOW)["mode"] == "no-change"


@pytest.mark.parametrize(
    "output",
    ["", "server0.local\t192.168.1.10\nserver0.local\t192.168.1.11", "wrong.local\t192.168.1.10"],
)
def test_mdns_discovery_rejects_ambiguous_response(evidence, monkeypatch, output):
    monkeypatch.setattr(
        MODULE.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, output)
    )
    with pytest.raises(MODULE.UnsafeEvidence):
        MODULE.resolve_mdns(evidence)


def test_mdns_timeout_cannot_produce_a_plan(evidence, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("avahi-resolve-host-name", 5)

    monkeypatch.setattr(MODULE.subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        MODULE.resolve_mdns(evidence)


@pytest.mark.parametrize(
    "scenario", ["healthy", "no_quorum", "stale", "malformed", "discovery", "timeout"]
)
def test_cli_entrypoint_results_and_evidence_preservation(
    evidence, tmp_path, monkeypatch, capsys, scenario
):
    """Exercise the actual command entrypoint, including exit codes and safe failures."""
    evidence["captured_at"] = datetime.now(timezone.utc).isoformat()
    if scenario == "no_quorum":
        for health in evidence["health"]:
            health["healthy"] = False
    elif scenario == "stale":
        evidence["captured_at"] = (datetime.now(timezone.utc) - timedelta(seconds=301)).isoformat()
    elif scenario == "malformed":
        evidence = {"private": "do-not-echo"}
    path = tmp_path / "evidence.json"
    original = json.dumps(evidence)
    path.write_text(original)
    calls = []

    def avahi(argv, **kwargs):
        calls.append(argv)
        assert argv[0:2] == ["avahi-resolve-host-name", "-4"]
        assert kwargs["timeout"] == 5 and kwargs["check"] is True
        if scenario == "timeout":
            raise subprocess.TimeoutExpired(argv, 5)
        addresses = {n["mdns_name"]: n["ethernet_ipv4"] for n in evidence["nodes"]}
        return subprocess.CompletedProcess(argv, 0, f"{argv[2]}\t{addresses[argv[2]]}\n")

    monkeypatch.setattr(subprocess, "run", avahi)
    argv = [str(SCRIPT), str(path)]
    if scenario in ("discovery", "timeout"):
        argv.append("--resolve-mdns")
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    successful = scenario in ("healthy", "discovery")
    assert exit_info.value.code == (0 if successful else 2)
    assert result["mode"] == ("no-change" if successful else "operator-intervention")
    assert result["automatic_actions"] == []
    assert result["candidates"] == []
    assert path.read_text() == original
    assert "do-not-echo" not in captured.out + captured.err
    assert len(calls) == {"discovery": 3, "timeout": 1}.get(scenario, 0)
