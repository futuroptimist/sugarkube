import argparse
import json
import subprocess
from pathlib import Path

import pytest

from scripts import tokenplace_incident_drill as drill


def args(tmp_path: Path, **changes):
    kubeconfig = tmp_path / "private" / "kubeconfig"
    kubeconfig.parent.mkdir(exist_ok=True)
    kubeconfig.write_text("fixture")
    values = dict(
        mode="metrics-oom",
        host="staging.token.place",
        kubeconfig=kubeconfig,
        context="sugar-staging",
        environment="staging",
        namespace="tokenplace",
        deployment="tokenplace",
        container="relay",
        current_image="registry.example/relay@sha256:" + "a" * 64,
        replacement_image="registry.example/relay@sha256:" + "b" * 64,
        rollback_image="registry.example/relay@sha256:" + "c" * 64,
        replicas=1,
        memory_limit="512Mi",
        service_monitor="tokenplace",
        run_id="drill-test",
        snapshot=tmp_path / "snapshot.json",
        evidence=tmp_path / "private-evidence" / "result.json",
        acknowledge_state_loss=True,
        dry_run=True,
    )
    values.update(changes)
    return argparse.Namespace(**values)


def snapshot(c, *, mode="metrics-oom", degraded=True):
    inv = drill.inventory("staging")
    classification = (
        {"termination_reason": "OOMKilled", "exit_code": 137}
        if mode == "metrics-oom"
        else {
            "route_statuses": {"root": 429, "metadata": 429, "livez": 200, "healthz": 200},
            "quota_validator_success": True,
        }
    )
    return {
        "deployment": {
            "namespace": c.namespace,
            "name": c.deployment,
            "container": c.container,
            "replicas": c.replicas,
            "image": c.current_image,
            "memory_limit": c.memory_limit,
            "metrics_mode": {"normal": "normal", "degraded": "degraded"} if degraded else None,
        },
        "service_monitor": {
            "namespace": inv.namespace,
            "name": inv.service_monitor,
            "selector_labels": dict(inv.selector_labels),
        },
        "probes": [
            {"namespace": "monitoring", "name": name, "route": route, "method": method}
            for _, name, route, method in inv.probes
        ],
        "classification": classification,
    }


def preflight(tmp_path, *, mode="metrics-oom", degraded=True, **changes):
    c = drill.validate(args(tmp_path, mode=mode, **changes))
    return drill.preflight_snapshot(mode, c, snapshot(c, mode=mode, degraded=degraded))


@pytest.mark.parametrize(
    "change",
    [
        {"environment": "prod"},
        {"context": "sugar-prod"},
        {"host": "token.place"},
        {"replicas": 0},
        {"current_image": "relay:latest"},
        {"replacement_image": "relay:latest"},
        {"rollback_image": "relay:latest"},
        {"memory_limit": "unknown"},
        {"acknowledge_state_loss": False},
        {"service_monitor": "anything-else"},
    ],
)
def test_static_preconditions_fail_closed(tmp_path, change):
    parsed = args(tmp_path, **change)
    if change == {"service_monitor": "anything-else"}:
        c = drill.validate(parsed)
        with pytest.raises(drill.DrillError, match="authoritative inventory"):
            drill.preflight_snapshot("metrics-oom", c, snapshot(c))
    else:
        with pytest.raises(drill.DrillError):
            drill.validate(parsed)


def test_typed_preflight_required_and_image_coordinates_are_exact(tmp_path):
    with pytest.raises(drill.DrillError, match="typed"):
        drill.build_plan({})
    checked = preflight(tmp_path)
    plan = drill.build_plan(checked)
    replace = next(a for a in plan["actions"] if a["stage"] == "replace")
    assert replace["command"][-1] == "relay=" + checked.coordinates.replacement_image
    assert replace["rollback"][-1] == "relay=" + checked.coordinates.rollback_image
    assert plan["expected_deployment"]["current_image"] == checked.coordinates.current_image


@pytest.mark.parametrize(
    "field,value",
    [("image", "wrong"), ("replicas", 2), ("memory_limit", "1Gi"), ("container", "wrong")],
)
def test_live_coordinate_drift_refuses_before_plan(tmp_path, field, value):
    c = drill.validate(args(tmp_path))
    data = snapshot(c)
    data["deployment"][field] = value
    with pytest.raises(drill.DrillError, match="Deployment coordinates"):
        drill.preflight_snapshot("metrics-oom", c, data)


def test_inventory_and_live_objects_are_exact(tmp_path):
    c = drill.validate(args(tmp_path))
    data = snapshot(c)
    data["service_monitor"]["selector_labels"] = {"app": "wrong"}
    with pytest.raises(drill.DrillError, match="ServiceMonitor"):
        drill.preflight_snapshot("metrics-oom", c, data)
    data = snapshot(c)
    data["probes"].append(data["probes"][0])
    with pytest.raises(drill.DrillError, match="Probe"):
        drill.preflight_snapshot("metrics-oom", c, data)


def test_oom_requires_reason_and_exit_code(tmp_path):
    c = drill.validate(args(tmp_path))
    for evidence in (
        {"termination_reason": "Error", "exit_code": 137},
        {"termination_reason": "OOMKilled", "exit_code": 1},
    ):
        data = snapshot(c)
        data["classification"] = evidence
        with pytest.raises(drill.DrillError, match="OOMKilled"):
            drill.preflight_snapshot("metrics-oom", c, data)


@pytest.mark.parametrize(
    "change",
    [
        {
            "route_statuses": {"root": 429, "metadata": 429, "livez": 500, "healthz": 200},
            "quota_validator_success": True,
        },
        {
            "route_statuses": {"root": 429, "metadata": 429, "livez": 200, "healthz": 200},
            "quota_validator_success": False,
        },
    ],
)
def test_quota_requires_healthy_routes_and_validator(tmp_path, change):
    c = drill.validate(args(tmp_path, mode="quota-exhaustion"))
    data = snapshot(c, mode="quota-exhaustion")
    data["classification"] = change
    with pytest.raises(drill.DrillError, match="quota classification"):
        drill.preflight_snapshot("quota-exhaustion", c, data)


def test_degraded_capability_and_fallback_are_deterministic(tmp_path):
    degraded = drill.build_plan(preflight(tmp_path, degraded=True))
    assert degraded["preflight"]["containment"] == "degraded-metrics"
    assert degraded["actions"][0]["command"][-1] == "TOKENPLACE_METRICS_MODE=degraded"
    fallback = drill.build_plan(preflight(tmp_path, degraded=False))
    assert fallback["preflight"]["containment"] == "servicemonitor-fallback"
    assert fallback["actions"][0]["resource"] == "servicemonitor/tokenplace"
    assert all("TOKENPLACE_METRICS_MODE" not in str(a) for a in fallback["actions"])


def test_live_preflight_calls_identity_first_and_binds_every_lookup(tmp_path, monkeypatch):
    c = drill.validate(args(tmp_path))
    normal = snapshot(c)
    deployment = {
        "metadata": {"namespace": c.namespace, "name": c.deployment},
        "spec": {
            "replicas": 1,
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "relay",
                            "image": c.current_image,
                            "resources": {"limits": {"memory": "512Mi"}},
                            "env": [{"name": "TOKENPLACE_METRICS_MODE", "value": "normal"}],
                        }
                    ]
                }
            },
        },
        "status": {
            "containerStatuses": [
                {
                    "name": "relay",
                    "lastState": {"terminated": {"reason": "OOMKilled", "exitCode": 137}},
                }
            ]
        },
    }
    monitor = {
        "metadata": {"namespace": "tokenplace", "name": "tokenplace"},
        "spec": {"selector": {"matchLabels": normal["service_monitor"]["selector_labels"]}},
    }
    probes = [
        {
            "metadata": {
                "namespace": p["namespace"],
                "name": p["name"],
            },
            "spec": {
                "targets": {
                    "staticConfig": {"static": ["https://staging.token.place" + p["route"]]}
                }
            },
        }
        for p in normal["probes"]
    ]
    replies = ["", json.dumps(deployment), json.dumps(monitor), *map(json.dumps, probes)]
    calls = []

    def runner(command):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, replies.pop(0), "")

    result = drill.preflight_live("metrics-oom", c, runner)
    assert "cluster_identity.py" in calls[0][1] and calls[0][-2:] == ["--env", "staging"]
    for call in calls[1:]:
        assert call[1:5] == ["--kubeconfig", str(c.kubeconfig), "--context", c.context]
    assert result.source == "live-authoritative"


def test_identity_failure_stops_before_kubectl(tmp_path):
    c = drill.validate(args(tmp_path))
    calls = []

    def runner(command):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, "", "")

    with pytest.raises(drill.DrillError, match="identity"):
        drill.preflight_live("metrics-oom", c, runner)
    assert len(calls) == 1


def test_preview_redacts_private_inputs_and_changes_nothing(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    rendered = json.dumps(plan)
    assert str(tmp_path) not in rendered
    assert "staging.token.place" not in rendered
    assert plan["non_executing_preview"] is True
    assert not any(plan["state_changes"].values())


def test_cli_accepts_private_evidence_location_outside_repo(tmp_path, monkeypatch, capsys):
    parsed = args(tmp_path)
    parsed.snapshot.write_text(json.dumps(snapshot(drill.validate(parsed))))
    monkeypatch.chdir(tmp_path)
    argv = []
    for key, value in vars(parsed).items():
        if key in {"acknowledge_state_loss", "dry_run"}:
            argv.append("--" + key.replace("_", "-"))
        else:
            argv += ["--" + key.replace("_", "-"), str(value)]
    assert drill.main(argv) == 0
    assert parsed.evidence.exists()
    assert str(parsed.evidence) not in capsys.readouterr().out


def test_duplicate_inventory_route_classes_are_rejected(monkeypatch):
    contract = drill.yaml.safe_load(
        (drill.ROOT / "config/observability/probe-quotas.yaml").read_text()
    )
    duplicate = next(
        p.copy()
        for p in contract["probes"]
        if p["application"] == "tokenplace" and p["environment"] == "staging"
    )
    contract["probes"].append(duplicate)
    original = drill.yaml.safe_load
    monkeypatch.setattr(drill.yaml, "safe_load", lambda _: contract)
    with pytest.raises(drill.DrillError, match="duplicate"):
        drill.inventory("staging")
    monkeypatch.setattr(drill.yaml, "safe_load", original)
