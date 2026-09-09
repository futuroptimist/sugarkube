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


def snapshot(c, *, mode="metrics-oom", degraded=True, metrics_mode_value="normal"):
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
            "metrics_mode_value": metrics_mode_value if degraded else "absent",
        },
        "service_monitor": {
            "namespace": inv.namespace,
            "name": inv.service_monitor,
            "selector_labels": dict(inv.selector_labels),
            "discovery_label": "kube-prometheus-stack",
            "incident_pause_label": None,
        },
        "probes": [
            {
                "namespace": "monitoring",
                "name": name,
                "route": route,
                "method": method,
                "discovery_label": "kube-prometheus-stack",
                "incident_pause_label": None,
            }
            for _, name, route, method in inv.probes
        ],
        "classification": classification,
    }


def preflight(
    tmp_path, *, mode="metrics-oom", degraded=True, metrics_mode_value="normal", **changes
):
    c = drill.validate(args(tmp_path, mode=mode, **changes))
    return drill.preflight_snapshot(
        mode,
        c,
        snapshot(c, mode=mode, degraded=degraded, metrics_mode_value=metrics_mode_value),
    )


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
    replace = next(a for a in plan["actions"] if a["id"] == "replace")
    assert replace["command"][-1] == "relay=" + checked.coordinates.replacement_image
    assert replace["rollback"][-1] == "relay=" + checked.coordinates.current_image
    assert replace["recovery_fallback"]["not_an_inverse"] is True
    assert replace["recovery_fallback"]["requires_capability_revalidation"] is True
    assert replace["recovery_fallback"]["command"][-1] == (
        "relay=" + checked.coordinates.rollback_image
    )
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
        "metadata": {"namespace": c.namespace, "name": c.deployment, "uid": "deployment-1"},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": "tokenplace"}},
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
    }
    monitor = {
        "metadata": {
            "namespace": "tokenplace",
            "name": "tokenplace",
            "labels": {"release": "kube-prometheus-stack"},
        },
        "spec": {"selector": {"matchLabels": normal["service_monitor"]["selector_labels"]}},
    }
    probes = [
        {
            "metadata": {
                "namespace": p["namespace"],
                "name": p["name"],
                "labels": {"release": "kube-prometheus-stack"},
            },
            "spec": {
                "targets": {
                    "staticConfig": {"static": ["https://staging.token.place" + p["route"]]}
                }
            },
        }
        for p in normal["probes"]
    ]
    replicaset = {
        "metadata": {
            "uid": "replicaset-1",
            "ownerReferences": [{"uid": "deployment-1", "controller": True}],
        }
    }
    pod = {
        "metadata": {
            "uid": "pod-private-1",
            "ownerReferences": [{"uid": "replicaset-1", "controller": True}],
        },
        "status": {
            "containerStatuses": [
                {
                    "name": "relay",
                    "restartCount": 2,
                    "lastState": {
                        "terminated": {
                            "reason": "OOMKilled",
                            "exitCode": 137,
                            "finishedAt": "2026-09-09T01:02:03Z",
                        }
                    },
                }
            ]
        },
    }
    events = {
        "items": [
            {
                "reason": "BackOff",
                "count": 2,
                "firstTimestamp": "2026-09-09T01:02:04Z",
                "lastTimestamp": "2026-09-09T01:03:04Z",
                "message": "private",
            }
        ]
    }
    replies = [
        "",
        json.dumps(deployment),
        json.dumps(monitor),
        *map(json.dumps, probes),
        json.dumps({"items": [replicaset]}),
        json.dumps({"items": [pod]}),
        json.dumps(events),
    ]
    calls = []

    def runner(command):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, replies.pop(0), "")

    result = drill.preflight_live("metrics-oom", c, runner)
    assert "cluster_identity.py" in calls[0][1] and calls[0][-2:] == ["--env", "staging"]
    for call in calls[1:]:
        assert call[1:5] == ["--kubeconfig", str(c.kubeconfig), "--context", c.context]
    assert result.source == "live-authoritative"
    rendered = json.dumps(drill.build_plan(result))
    assert "pod-private-1" not in rendered and "private" not in rendered
    assert '"reason": "BackOff"' in rendered


@pytest.mark.parametrize("pod_count", [0, 2])
def test_live_oom_requires_one_owned_candidate(tmp_path, pod_count):
    c = drill.validate(args(tmp_path))
    deployment = {
        "metadata": {"uid": "deployment-1"},
        "spec": {"selector": {"matchLabels": {"app": "tokenplace"}}},
    }
    rs = {
        "metadata": {
            "uid": "rs-1",
            "ownerReferences": [{"uid": "deployment-1", "controller": True}],
        }
    }
    pod = {
        "metadata": {"uid": "pod-1", "ownerReferences": [{"uid": "rs-1", "controller": True}]},
        "status": {
            "containerStatuses": [
                {
                    "name": c.container,
                    "restartCount": 1,
                    "lastState": {
                        "terminated": {
                            "reason": "OOMKilled",
                            "exitCode": 137,
                            "finishedAt": "2026-09-09T01:02:03Z",
                        }
                    },
                }
            ]
        },
    }
    replies = [json.dumps({"items": [rs]}), json.dumps({"items": [pod] * pod_count})]

    def runner(command):
        return subprocess.CompletedProcess(command, 0, replies.pop(0), "")

    with pytest.raises(drill.DrillError, match="missing or ambiguous"):
        drill._observe_live_oom(c, deployment, ["kubectl"], runner)


def test_live_oom_rejects_wrong_owner_and_malformed_termination(tmp_path):
    c = drill.validate(args(tmp_path))
    deployment = {
        "metadata": {"uid": "deployment-1"},
        "spec": {"selector": {"matchLabels": {"app": "tokenplace"}}},
    }
    rs = {
        "metadata": {
            "uid": "rs-1",
            "ownerReferences": [{"uid": "deployment-1", "controller": True}],
        }
    }
    for owner, finished, match in (
        ("stale", "2026-09-09T01:02:03Z", "ownership"),
        ("rs-1", "bad", "timestamp"),
    ):
        pod = {
            "metadata": {"uid": "pod-1", "ownerReferences": [{"uid": owner, "controller": True}]},
            "status": {
                "containerStatuses": [
                    {
                        "name": c.container,
                        "restartCount": 1,
                        "lastState": {
                            "terminated": {
                                "reason": "OOMKilled",
                                "exitCode": 137,
                                "finishedAt": finished,
                            }
                        },
                    }
                ]
            },
        }
        replies = [json.dumps({"items": [rs]}), json.dumps({"items": [pod]})]

        def runner(command):
            return subprocess.CompletedProcess(command, 0, replies.pop(0), "")

        with pytest.raises(drill.DrillError, match=match):
            drill._observe_live_oom(c, deployment, ["kubectl"], runner)


def test_live_quota_runs_validator_then_status_only_requests():
    calls = []
    replies = ["", "429", "429", "200", "200"]

    def runner(command):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, replies.pop(0), "")

    evidence = drill._observe_live_quota(runner)
    assert "validate_probe_quotas.py" in calls[0][1]
    assert evidence["route_statuses"] == {
        "root": 429,
        "metadata": 429,
        "livez": 200,
        "healthz": 200,
    }
    assert all("--output" in call and "/dev/null" in call for call in calls[1:])


def test_live_quota_fails_closed_on_validator_or_route_status():
    def failed_validator(command):
        return subprocess.CompletedProcess(command, 1, "", "")

    with pytest.raises(drill.DrillError, match="quota validation"):
        drill._observe_live_quota(failed_validator)
    replies = ["", "200", "429", "200", "200"]

    def wrong_status(command):
        return subprocess.CompletedProcess(command, 0, replies.pop(0), "")

    evidence = drill._observe_live_quota(wrong_status)
    assert evidence["route_statuses"]["root"] == 200


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


def test_metrics_plan_has_typed_ordered_gates_and_metrics_last(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    ids = [action["id"] for action in plan["actions"]]
    assert ids == [
        "pause-metrics",
        "replace",
        "workload-readiness",
        "compute-registration",
        "compute-polling",
        "encrypted-e2ee",
        "preserve-root",
        "preserve-metadata",
        "metrics-exit",
        "restore-metrics",
        "observe-metrics",
    ]
    assert all(
        action["depends_on"] == [ids[index - 1]]
        for index, action in enumerate(plan["actions"][1:], 1)
    )
    workload = next(action for action in plan["actions"] if action["id"] == "workload-readiness")
    assert workload["duration"] == {"value": 5, "unit": "minutes"}
    assert {check["metric"] for check in workload["checks"]} >= {
        "ready_replicas",
        "image_digest",
        "memory_limit",
    }
    assert workload["on_failure"][-1].endswith(preflight(tmp_path).coordinates.current_image)
    for action in plan["actions"]:
        if action["type"] == "gate":
            assert "command" not in action


def test_quota_restoration_has_exact_inverse_and_preserves_health(tmp_path):
    plan = drill.build_plan(preflight(tmp_path, mode="quota-exhaustion"))
    ids = [action["id"] for action in plan["actions"]]
    assert ids.index("encrypted-e2ee") < ids.index("quota-validator") < ids.index("restore-root")
    assert ids.index("restore-root") < ids.index("observe-root") < ids.index("restore-metadata")
    validator = next(action for action in plan["actions"] if action["id"] == "quota-validator")
    assert validator["checks"][0]["argv"] == [
        "python3",
        "scripts/validate_probe_quotas.py",
        "--env",
        "staging",
        "--probes",
        "clusters/staging/observability/probes/public-apps.yaml",
    ]
    assert validator["on_failure"] == {
        "outcome": "hold-current-containment",
        "root": "paused",
        "metadata": "paused",
        "mutation": None,
    }
    assert "command" not in validator
    assert (
        ids.index("restore-metadata")
        < ids.index("observe-metadata")
        < ids.index("preserve-metrics-last")
    )
    assert ids[-1] == "observe-metrics"
    for label in ("root", "metadata"):
        restore = next(action for action in plan["actions"] if action["id"] == f"restore-{label}")
        observation = next(
            action for action in plan["actions"] if action["id"] == f"observe-{label}"
        )
        assert "release=kube-prometheus-stack" in restore["command"]
        assert observation["duration"] == {"value": 15, "unit": "minutes"}
        assert observation["on_failure"] == restore["inverse"]
        assert observation["preserves"] == ["probe/livez", "probe/healthz"]


def test_numeric_observation_thresholds_and_metrics_exit(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    ids = [action["id"] for action in plan["actions"]]
    assert (
        ids.index("preserve-metadata")
        < ids.index("metrics-exit")
        < ids.index("restore-metrics")
        < ids.index("observe-metrics")
    )
    exit_gate = next(action for action in plan["actions"] if action["id"] == "metrics-exit")
    exit_checks = {check["metric"]: check for check in exit_gate["checks"]}
    assert exit_checks["authenticated_scrape"]["value"] is True
    assert exit_checks["active_series_vs_baseline"]["value"] == 10
    assert exit_checks["scrape_samples_vs_baseline"]["value"] == 10
    assert exit_checks["restart_increase"]["value"] == 0
    assert exit_checks["new_oomkilled_137"]["value"] == 0
    assert exit_checks["memory_working_set"] == {
        "metric": "memory_working_set",
        "operator": "lt",
        "value": 70,
        "unit": "percent_of_limit",
        "window": {"value": 15, "unit": "minutes"},
    }
    assert exit_gate["on_failure"] == {
        "outcome": "hold-current-containment",
        "metrics": "paused",
        "mutation": None,
    }
    assert "command" not in exit_gate
    observation = plan["actions"][-1]
    checks = {check["metric"]: check for check in observation["checks"]}
    assert observation["duration"] == {"value": 30, "unit": "minutes"}
    assert checks["route_429_rate"]["value"] == 1
    assert checks["route_429_rate"]["window"] == {"value": 5, "unit": "minutes"}
    assert checks["route_5xx_rate"]["value"] == 1
    assert checks["scrape_health"]["value"] == 100
    assert checks["active_series_vs_baseline"]["value"] == 10
    assert checks["scrape_samples_vs_baseline"]["value"] == 10
    assert checks["memory_working_set"]["value"] == 70
    assert checks["memory_working_set"]["window"] == {"value": 15, "unit": "minutes"}


def test_exact_old_metrics_states_and_discovery_labels(tmp_path):
    already_degraded = drill.build_plan(
        preflight(tmp_path, degraded=True, metrics_mode_value="degraded")
    )
    assert already_degraded["preflight"]["containment"] == "degraded-metrics"
    assert "pause-metrics" not in [action["id"] for action in already_degraded["actions"]]
    assert "restore-metrics" not in [action["id"] for action in already_degraded["actions"]]

    fallback = drill.build_plan(preflight(tmp_path, degraded=False))
    pause = fallback["actions"][0]
    exit_gate = next(action for action in fallback["actions"] if action["id"] == "metrics-exit")
    restore = next(action for action in fallback["actions"] if action["id"] == "restore-metrics")
    observation = next(
        action for action in fallback["actions"] if action["id"] == "observe-metrics"
    )
    exit_checks = {check["metric"]: check for check in exit_gate["checks"]}
    assert "scrape_health" not in exit_checks
    assert exit_checks["authenticated_scrape"] == {
        "metric": "authenticated_scrape",
        "operator": "eq",
        "value": True,
        "unit": "boolean",
        "source": "direct-authenticated-target",
    }
    assert fallback["actions"].index(exit_gate) < fallback["actions"].index(restore)
    assert {check["metric"] for check in observation["checks"]} >= {"scrape_health"}
    assert pause["old_state"] == {
        "release": "kube-prometheus-stack",
        "sugarkube.dev/incident-paused": None,
    }
    assert restore["command"] == pause["inverse"]
    assert restore["inverse"] == pause["command"]
    assert observation["on_failure"] == pause["command"]


def test_missing_old_discovery_state_fails_closed(tmp_path):
    c = drill.validate(args(tmp_path))
    data = snapshot(c)
    data["service_monitor"]["discovery_label"] = None
    with pytest.raises(drill.DrillError, match="ServiceMonitor"):
        drill.preflight_snapshot("metrics-oom", c, data)
