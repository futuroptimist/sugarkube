import argparse
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import tokenplace_incident_drill as drill


def args(tmp_path: Path, **changes):
    kubeconfig = tmp_path / "private" / "kubeconfig"
    kubeconfig.parent.mkdir(exist_ok=True)
    kubeconfig.write_text("fixture")
    (tmp_path / "private-evidence").mkdir(exist_ok=True)
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
        live_preflight=False,
        evidence=tmp_path / "private-evidence" / "result.json",
        acknowledge_state_loss=True,
        lifecycle="real-incident",
        incident_image=None,
        acknowledge_staging_fault_injection=False,
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


@pytest.mark.parametrize(
    "change,message",
    [
        ({"kubeconfig": Path("/missing/kubeconfig")}, "kubeconfig"),
        (
            {"replacement_image": "registry.example/relay@sha256:" + "a" * 64},
            "distinct",
        ),
        ({"run_id": "unsafe_name"}, "safe Kubernetes name"),
    ],
)
def test_additional_static_preconditions_are_covered(tmp_path, change, message):
    with pytest.raises(drill.DrillError, match=message):
        drill.validate(args(tmp_path, **change))


@pytest.mark.parametrize(
    "capability,value,message",
    [
        ({"normal": "normal", "degraded": "unsupported"}, "normal", "contract"),
        ({"normal": "normal", "degraded": "degraded"}, "unsupported", "inverted"),
    ],
)
def test_metrics_capability_must_be_supported_and_invertible(tmp_path, capability, value, message):
    c = drill.validate(args(tmp_path))
    data = snapshot(c)
    data["deployment"]["metrics_mode"] = capability
    data["deployment"]["metrics_mode_value"] = value
    with pytest.raises(drill.DrillError, match=message):
        drill.preflight_snapshot("metrics-oom", c, data)


@pytest.mark.parametrize(
    "result",
    [
        subprocess.CompletedProcess([], 1, "", ""),
        subprocess.CompletedProcess([], 0, "not-json", ""),
        subprocess.CompletedProcess([], 0, "[]", ""),
    ],
)
def test_runner_json_refuses_failed_or_malformed_results(result):
    with pytest.raises(drill.DrillError, match="observation failed"):
        drill._runner_json(lambda _command: result, ["ignored"], "observation failed")


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


def test_staging_rehearsal_has_separate_identities_and_live_oom_gate(tmp_path):
    parsed = args(
        tmp_path,
        lifecycle="staging-rehearsal",
        incident_image="registry.example/relay@sha256:" + "d" * 64,
        acknowledge_staging_fault_injection=True,
    )
    c = drill.validate(parsed)
    healthy = snapshot(c)
    healthy["classification"] = {}
    plan = drill.build_plan(drill.preflight_snapshot("metrics-oom", c, healthy))

    assert plan["lifecycle"] == "staging-rehearsal"
    assert plan["preflight"]["classification"] == {"oom_status": "not-yet-observed"}
    assert plan["preflight"]["offline_fixture_authoritative"] is False
    assert [action["id"] for action in plan["actions"][:3]] == [
        "inject-oom-stimulus",
        "observe-authentic-oom",
        "pause-metrics",
    ]
    stimulus = plan["actions"][0]
    assert stimulus["command"][-1] == "relay=" + c.incident_image
    assert stimulus["inverse"][-1] == "relay=" + c.current_image
    replace = next(action for action in plan["actions"] if action["id"] == "replace")
    assert replace["old_state"] == {"image": c.incident_image}
    assert replace["inverse_state"] == {"image": c.current_image}
    assert replace["inverse"][-1] == "relay=" + c.current_image
    assert (
        len(
            {
                plan["expected_deployment"][key]
                for key in (
                    "current_image",
                    "incident_image",
                    "replacement_image",
                    "rollback_image",
                )
            }
        )
        == 4
    )


@pytest.mark.parametrize(
    "changes,message",
    [
        ({"acknowledge_staging_fault_injection": False}, "fault-injection"),
        ({"incident_image": None}, "incident image"),
        ({"incident_image": "registry.example/relay@sha256:" + "a" * 64}, "distinct"),
        ({"environment": "production"}, "staging"),
    ],
)
def test_staging_rehearsal_authorization_and_coordinates_fail_closed(tmp_path, changes, message):
    values = {
        "lifecycle": "staging-rehearsal",
        "incident_image": "registry.example/relay@sha256:" + "d" * 64,
        "acknowledge_staging_fault_injection": True,
    }
    values.update(changes)
    with pytest.raises(drill.DrillError, match=message):
        drill.validate(args(tmp_path, **values))


def test_real_incident_rejects_rehearsal_controls(tmp_path):
    with pytest.raises(drill.DrillError, match="require staging-rehearsal"):
        drill.validate(args(tmp_path, incident_image="registry.example/relay@sha256:" + "d" * 64))


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
        },
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": c.container,
                            "image": c.current_image,
                            "resources": {"limits": {"memory": c.memory_limit}},
                        }
                    ]
                }
            }
        },
    }
    pod = {
        "metadata": {
            "uid": "pod-private-1",
            "ownerReferences": [{"uid": "replicaset-1", "controller": True}],
        },
        "spec": {
            "containers": [
                {
                    "name": c.container,
                    "image": c.current_image,
                    "resources": {"limits": {"memory": c.memory_limit}},
                }
            ]
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
def test_live_oom_rejects_unconverged_pod_count(tmp_path, pod_count):
    c = drill.validate(args(tmp_path))
    deployment = {
        "metadata": {"uid": "deployment-1"},
        "spec": {"selector": {"matchLabels": {"app": "tokenplace"}}},
    }
    rs = {
        "metadata": {
            "uid": "rs-1",
            "ownerReferences": [{"uid": "deployment-1", "controller": True}],
        },
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": c.container,
                            "image": c.current_image,
                            "resources": {"limits": {"memory": c.memory_limit}},
                        }
                    ]
                }
            }
        },
    }
    pod = {
        "metadata": {"uid": "pod-1", "ownerReferences": [{"uid": "rs-1", "controller": True}]},
        "spec": {
            "containers": [
                {
                    "name": c.container,
                    "image": c.current_image,
                    "resources": {"limits": {"memory": c.memory_limit}},
                }
            ]
        },
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

    with pytest.raises(drill.DrillError, match="unconverged"):
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
        },
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": c.container,
                            "image": c.current_image,
                            "resources": {"limits": {"memory": c.memory_limit}},
                        }
                    ]
                }
            }
        },
    }
    for owner, finished, match in (
        ("stale", "2026-09-09T01:02:03Z", "ownership"),
        ("rs-1", "bad", "timestamp"),
    ):
        pod = {
            "metadata": {"uid": "pod-1", "ownerReferences": [{"uid": owner, "controller": True}]},
            "spec": {
                "containers": [
                    {
                        "name": c.container,
                        "image": c.current_image,
                        "resources": {"limits": {"memory": c.memory_limit}},
                    }
                ]
            },
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


@pytest.mark.parametrize(
    ("case", "match"),
    [
        ("old-replicaset-pod", "ownership"),
        ("replicaset-image", "current ReplicaSet"),
        ("replicaset-memory", "current ReplicaSet"),
        ("pod-image", "coordinates"),
        ("pod-memory", "coordinates"),
        ("terminating", "terminating"),
        ("replica-count", "unconverged"),
    ],
)
def test_live_oom_requires_a_converged_reviewed_workload(tmp_path, case, match):
    c = drill.validate(args(tmp_path))
    deployment = {
        "metadata": {"uid": "deployment-1"},
        "spec": {"selector": {"matchLabels": {"app": "tokenplace"}}},
    }

    def replicaset(uid="rs-current", image=None, memory=None):
        return {
            "metadata": {
                "uid": uid,
                "ownerReferences": [{"uid": "deployment-1", "controller": True}],
            },
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": c.container,
                                "image": image or c.current_image,
                                "resources": {"limits": {"memory": memory or c.memory_limit}},
                            }
                        ]
                    }
                }
            },
        }

    def pod(owner="rs-current", image=None, memory=None):
        return {
            "metadata": {
                "uid": "pod-private",
                "ownerReferences": [{"uid": owner, "controller": True}],
            },
            "spec": {
                "containers": [
                    {
                        "name": c.container,
                        "image": image or c.current_image,
                        "resources": {"limits": {"memory": memory or c.memory_limit}},
                    }
                ]
            },
            "status": {"containerStatuses": []},
        }

    replicasets = [replicaset()]
    pods = [pod()]
    if case == "old-replicaset-pod":
        replicasets.append(replicaset("rs-old", c.rollback_image))
        pods = [pod("rs-old", c.rollback_image)]
    elif case == "replicaset-image":
        replicasets = [replicaset(image=c.rollback_image)]
    elif case == "replicaset-memory":
        replicasets = [replicaset(memory="1Gi")]
    elif case == "pod-image":
        pods = [pod(image=c.rollback_image)]
    elif case == "pod-memory":
        pods = [pod(memory="1Gi")]
    elif case == "terminating":
        pods[0]["metadata"]["deletionTimestamp"] = "2026-09-09T01:00:00Z"
    elif case == "replica-count":
        pods = []
    replies = [json.dumps({"items": replicasets}), json.dumps({"items": pods})]

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
        if value is None or value is False:
            continue
        if key in {"acknowledge_state_loss", "acknowledge_staging_fault_injection", "dry_run"}:
            argv.append("--" + key.replace("_", "-"))
        else:
            argv += ["--" + key.replace("_", "-"), str(value)]
    assert drill.main(argv) == 0
    assert parsed.evidence.exists()
    captured = capsys.readouterr()
    assert str(parsed.evidence) not in captured.out + captured.err
    published = json.loads(parsed.evidence.read_text())
    assert published == json.loads(captured.out)
    assert published["state_changes"]["repository"] is False
    assert parsed.evidence.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("kind", ["relative", "repository"])
def test_cli_refuses_non_private_evidence_targets_without_disclosure(
    tmp_path, monkeypatch, capsys, kind
):
    parsed = args(tmp_path)
    parsed.snapshot.write_text(json.dumps(snapshot(drill.validate(parsed))))
    target = Path("private-result.json") if kind == "relative" else drill.ROOT / "result.json"
    parsed.evidence = target
    argv = []
    for key, value in vars(parsed).items():
        if value is None or value is False:
            continue
        if key in {"acknowledge_state_loss", "acknowledge_staging_fault_injection", "dry_run"}:
            argv.append("--" + key.replace("_", "-"))
        else:
            argv += ["--" + key.replace("_", "-"), str(value)]
    monkeypatch.chdir(tmp_path)
    assert drill.main(argv) == 2
    captured = capsys.readouterr()
    assert str(target) not in captured.out + captured.err
    assert not (tmp_path / "private-result.json").exists()
    assert not (drill.ROOT / "result.json").exists()


def test_existing_evidence_file_and_symlink_are_never_overwritten(tmp_path):
    (tmp_path / "private-evidence").mkdir()
    existing = tmp_path / "private-evidence" / "existing.json"
    existing.write_text("original")
    with pytest.raises(drill.DrillError, match="new regular file"):
        drill.validate(args(tmp_path, evidence=existing))
    assert existing.read_text() == "original"

    destination = tmp_path / "private-evidence" / "destination.json"
    destination.write_text("destination")
    link = tmp_path / "private-evidence" / "link.json"
    link.symlink_to(destination)
    with pytest.raises(drill.DrillError, match="new regular file"):
        drill.validate(args(tmp_path, evidence=link))
    assert link.is_symlink()
    assert destination.read_text() == "destination"


def test_missing_evidence_parent_is_not_created(tmp_path):
    target = tmp_path / "missing" / "result.json"
    with pytest.raises(drill.DrillError, match="safely resolved"):
        drill.validate(args(tmp_path, evidence=target))
    assert not target.parent.exists()


@pytest.mark.parametrize("failure", ["write", "publish"])
def test_evidence_publication_failure_leaves_no_files(tmp_path, monkeypatch, failure):
    directory = tmp_path / "private-evidence"
    directory.mkdir()
    target = directory / "failed.json"
    reached = {failure: 0}

    if failure == "write":

        def fail_fsync(_fd):
            reached["write"] += 1
            raise OSError

        monkeypatch.setattr(drill.os, "fsync", fail_fsync)
    else:

        def fail_link(_source, _target):
            reached["publish"] += 1
            raise OSError

        monkeypatch.setattr(drill.os, "link", fail_link)

    with pytest.raises(OSError):
        drill._publish_evidence(target, '{"complete": true}\n')
    assert reached[failure] == 1
    assert not target.exists()
    assert list(directory.glob(".tokenplace-evidence-*")) == []


def test_evidence_publication_race_does_not_replace_existing_target(tmp_path):
    directory = tmp_path / "private-evidence"
    directory.mkdir()
    target = directory / "result.json"
    drill._validate_evidence_target(target)
    target.write_text("competing publication")

    with pytest.raises(FileExistsError):
        drill._publish_evidence(target, '{"complete": true}\n')

    assert target.read_text() == "competing publication"
    assert list(directory.glob(".tokenplace-evidence-*")) == []


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


def test_offline_rehearsal_plan_cannot_be_executed(tmp_path):
    parsed = args(
        tmp_path,
        lifecycle="staging-rehearsal",
        incident_image="registry.example/relay@sha256:" + "d" * 64,
        acknowledge_staging_fault_injection=True,
    )
    c = drill.validate(parsed)
    healthy = snapshot(c)
    healthy["classification"] = {}
    plan = drill.build_plan(drill.preflight_snapshot("metrics-oom", c, healthy))
    path = tmp_path / "preview.json"
    path.write_text(json.dumps(plan))
    with pytest.raises(drill.DrillError, match="cannot be executed"):
        drill._load_execution_plan(path)


def test_authentic_oom_window_starts_at_stimulus_intent():
    records = [
        {
            "operation": "execute",
            "stage": "inject-oom-stimulus",
            "phase": "intent",
            "recorded_at": "2026-09-11T12:00:00Z",
        },
        {
            "operation": "execute",
            "stage": "inject-oom-stimulus",
            "phase": "completed",
            "recorded_at": "2026-09-11T12:00:05Z",
        },
    ]

    assert drill._stimulus_not_before(records) == datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def test_rehearsal_replacement_inverse_matches_healthy_baseline(tmp_path):
    parsed = args(
        tmp_path,
        lifecycle="staging-rehearsal",
        incident_image="registry.example/relay@sha256:" + "d" * 64,
        acknowledge_staging_fault_injection=True,
    )
    coordinates = drill.validate(parsed)
    healthy = snapshot(coordinates)
    healthy["classification"] = {}
    plan = drill.build_plan(drill.preflight_snapshot("metrics-oom", coordinates, healthy))
    replace = next(action for action in plan["actions"] if action["id"] == "replace")
    observed = {
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {"name": coordinates.container, "image": coordinates.current_image}
                    ]
                }
            }
        }
    }

    assert drill._action_matches(plan, replace, observed, post=False)


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


def execution_files(tmp_path, plan):
    plan_path = tmp_path / "immutable-plan.json"
    plan_path.write_text(json.dumps(plan))
    journal = tmp_path / "private-journal"
    journal.mkdir()
    kubeconfig = tmp_path / "execution-kubeconfig"
    kubeconfig.write_text("fixture")
    return argparse.Namespace(
        execute_stage=None,
        rollback_stage=None,
        cleanup=False,
        plan=plan_path,
        journal=journal,
        kubeconfig=kubeconfig,
        gate_evidence=None,
    )


def gate_evidence(plan, gate, now=None):
    now = now or datetime.now(timezone.utc)
    windows = [gate.get("duration", {"value": 0})["value"]]
    windows += [check.get("window", {"value": 0})["value"] for check in gate["checks"]]
    start = now - timedelta(minutes=max(windows))
    stamp = lambda value: value.isoformat(timespec="seconds").replace("+00:00", "Z")
    checks = {}
    for check in gate["checks"]:
        value = check["value"]
        if check["operator"] == "lt":
            value -= 1
        item = {
            "value": value,
            "observed_from": stamp(start),
            "observed_until": stamp(now),
        }
        if "source" in check:
            item["source"] = check["source"]
        checks[check["metric"]] = item
    return {
        "schema_version": 1,
        "run_id": plan["run_id"],
        "plan_digest": plan["plan_digest"],
        "stage": gate["id"],
        "observed_from": stamp(start),
        "observed_until": stamp(now),
        "checks": checks,
    }


def execution_runner(plan, calls, marker=None, initial_image=None):
    expected = plan["expected_deployment"]
    state = {
        "image": initial_image or expected["current_image"],
        "metrics_mode": "normal",
        "paused": False,
        "marker": marker,
    }
    deployment = {
        "spec": {
            "replicas": expected["replicas"],
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": expected["container"],
                            "image": state["image"],
                            "resources": {"limits": {"memory": expected["memory_limit"]}},
                            "env": [
                                {
                                    "name": "TOKENPLACE_METRICS_MODE",
                                    "value": state["metrics_mode"],
                                }
                            ],
                        }
                    ]
                }
            },
        }
    }

    def run(command):
        calls.append(command)
        if "cluster_identity.py" in " ".join(command):
            return subprocess.CompletedProcess(command, 0, "", "")
        if "deployment" in command and "get" in command:
            container = deployment["spec"]["template"]["spec"]["containers"][0]
            container["image"] = state["image"]
            container["env"][0]["value"] = state["metrics_mode"]
            return subprocess.CompletedProcess(command, 0, json.dumps(deployment), "")
        if "get" in command and ("probe" in command or "servicemonitor" in command):
            labels = (
                {"sugarkube.dev/incident-paused": "true"}
                if state["paused"]
                else {"release": "kube-prometheus-stack"}
            )
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"metadata": {"labels": labels}}), ""
            )
        if "configmap" in command and "get" in command:
            return subprocess.CompletedProcess(
                command, 0, json.dumps(state["marker"]) if state["marker"] else "", ""
            )
        if command[0] == "curl":
            return subprocess.CompletedProcess(command, 0, "200", "")
        if "label" in command:
            state["paused"] = "release-" in command
        if "set" in command and "env" in command:
            state["metrics_mode"] = command[-1].split("=", 1)[1]
        if "set" in command and "image" in command:
            state["image"] = command[-1].split("=", 1)[1]
        if "configmap" in command and "create" in command:
            state["marker"] = {
                "data": {"run-id": plan["run_id"], "plan-digest": plan["plan_digest"]}
            }
        if "configmap" in command and "delete" in command:
            state["marker"] = None
        return subprocess.CompletedProcess(command, 0, "", "")

    return run


def test_execution_plan_digest_tampering_fails_before_runner(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    plan["expected_deployment"]["replicas"] = 99
    parsed = execution_files(tmp_path, plan)
    calls = []
    with pytest.raises(drill.DrillError, match="digest"):
        drill.execute_operation(parsed, execution_runner(plan, calls))
    assert calls == []


def test_marker_is_unique_one_stage_and_resumable(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    parsed = execution_files(tmp_path, plan)
    parsed.execute_stage = "marker"
    calls = []
    result = drill.execute_operation(parsed, execution_runner(plan, calls))
    assert result == {"status": "completed", "stage": "marker"}
    mutations = [command for command in calls if "create" in command or "delete" in command]
    assert len(mutations) == 1
    assert mutations[0][mutations[0].index("configmap") + 1].startswith(
        "tokenplace-drill-drill-test-"
    )
    assert f"--from-literal=run-id={plan['run_id']}" in mutations[0]
    assert f"--from-literal=plan-digest={plan['plan_digest']}" in mutations[0]
    assert "--labels" not in mutations[0]

    marker = {
        "metadata": {
            "labels": {
                "sugarkube.dev/run-id": plan["run_id"],
                "sugarkube.dev/plan-digest": plan["plan_digest"],
            }
        },
        "data": {"run-id": plan["run_id"], "plan-digest": plan["plan_digest"]},
    }
    calls.clear()
    result = drill.execute_operation(parsed, execution_runner(plan, calls, marker))
    assert result["status"] == "already-completed"
    assert not any("create" in command or "delete" in command for command in calls)


def test_out_of_order_and_marker_collision_fail_closed(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    parsed = execution_files(tmp_path, plan)
    parsed.execute_stage = plan["actions"][0]["id"]
    calls = []
    with pytest.raises(drill.DrillError, match="marker"):
        drill.execute_operation(parsed, execution_runner(plan, calls))

    parsed.execute_stage = "marker"
    wrong = {
        "metadata": {"labels": {"sugarkube.dev/run-id": "another-run"}},
        "data": {},
    }
    with pytest.raises(drill.DrillError, match="ownership"):
        drill.execute_operation(parsed, execution_runner(plan, [], wrong))


def test_gate_evidence_is_typed_and_never_runs_a_mutation(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    gate = next(action for action in plan["actions"] if action["type"] == "gate")
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    passing = gate_evidence(plan, gate, now)
    assert drill._evidence_passes(plan, gate, passing, now)[0] is True
    failing = json.loads(json.dumps(passing))
    failing["checks"][gate["checks"][0]["metric"]]["value"] = -1
    assert drill._evidence_passes(plan, gate, failing, now)[0] is False
    with pytest.raises(drill.DrillError, match="malformed"):
        drill._evidence_passes(plan, gate, {}, now)


@pytest.mark.parametrize("mode", drill.MODES)
def test_versioned_evidence_covers_all_gate_durations_and_sources(tmp_path, mode):
    plan = drill.build_plan(preflight(tmp_path, mode=mode))
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    durations = set()
    for gate in (action for action in plan["actions"] if action["type"] == "gate"):
        durations.add(gate.get("duration", {"value": 0})["value"])
        assert drill._evidence_passes(plan, gate, gate_evidence(plan, gate, now), now)[0]
    assert durations >= {0, 5, 15, 30}


@pytest.mark.parametrize("field", ["run_id", "plan_digest", "stage"])
def test_gate_evidence_is_bound_to_exact_plan_identity(tmp_path, field):
    plan = drill.build_plan(preflight(tmp_path))
    gate = next(action for action in plan["actions"] if action["type"] == "gate")
    evidence = gate_evidence(plan, gate)
    evidence[field] = "f" * 64 if field == "plan_digest" else "wrong"
    with pytest.raises(drill.DrillError, match="belong"):
        drill._evidence_passes(plan, gate, evidence)


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda evidence, gate: evidence.update(extra=True), "malformed"),
        (lambda evidence, gate: evidence["checks"].pop(gate["checks"][0]["metric"]), "metric"),
        (lambda evidence, gate: evidence["checks"].update(extra={}), "metric"),
        (lambda evidence, gate: evidence.update(observed_until="not-a-time"), "timestamp"),
        (
            lambda evidence, gate: evidence.update(
                observed_from=evidence["observed_until"], observed_until=evidence["observed_from"]
            ),
            "interval",
        ),
    ],
)
def test_gate_evidence_rejects_fields_metrics_and_timestamps(tmp_path, change, message):
    plan = drill.build_plan(preflight(tmp_path))
    gate = next(action for action in plan["actions"] if action["type"] == "gate")
    evidence = gate_evidence(plan, gate)
    change(evidence, gate)
    with pytest.raises(drill.DrillError, match=message):
        drill._evidence_passes(plan, gate, evidence)


def test_gate_evidence_rejects_stale_future_short_window_and_wrong_source(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    gate = next(
        action
        for action in plan["actions"]
        if action["type"] == "gate" and any("source" in check for check in action["checks"])
    )
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    evidence = gate_evidence(plan, gate, now)
    with pytest.raises(drill.DrillError, match="stale"):
        drill._evidence_passes(plan, gate, evidence, now + timedelta(minutes=6))
    with pytest.raises(drill.DrillError, match="invalid"):
        drill._evidence_passes(plan, gate, evidence, now - timedelta(seconds=1))
    metric = next(check["metric"] for check in gate["checks"] if "source" in check)
    evidence["checks"][metric]["source"] = "prometheus"
    with pytest.raises(drill.DrillError, match="source"):
        drill._evidence_passes(plan, gate, evidence, now)


def test_gate_evidence_rejects_stale_individual_check(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    gate = next(
        action
        for action in plan["actions"]
        if action["type"] == "gate" and action.get("duration", {}).get("value") == 30
    )
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    evidence = gate_evidence(plan, gate, now)
    metric = gate["checks"][0]["metric"]
    evidence["checks"][metric]["observed_from"] = stamp = "2026-09-10T11:30:00Z"
    evidence["checks"][metric]["observed_until"] = "2026-09-10T11:35:00Z"
    assert evidence["observed_from"] == stamp
    with pytest.raises(drill.DrillError, match="check is stale"):
        drill._evidence_passes(plan, gate, evidence, now)


def test_gate_evidence_rejects_short_duration_window_and_non_utc(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    gate = next(
        action
        for action in plan["actions"]
        if action["type"] == "gate" and action.get("duration", {}).get("value") == 15
    )
    evidence = gate_evidence(plan, gate)
    evidence["observed_from"] = evidence["observed_until"]
    with pytest.raises(drill.DrillError, match="duration"):
        drill._evidence_passes(plan, gate, evidence)
    gate = next(
        action
        for action in plan["actions"]
        if action["type"] == "gate" and any("window" in check for check in action["checks"])
    )
    evidence = gate_evidence(plan, gate)
    windowed = next(check for check in gate["checks"] if "window" in check)
    evidence["checks"][windowed["metric"]]["observed_from"] = evidence["checks"][
        windowed["metric"]
    ]["observed_until"]
    with pytest.raises(drill.DrillError, match="window"):
        drill._evidence_passes(plan, gate, evidence)
    evidence = gate_evidence(plan, gate)
    evidence["observed_until"] = evidence["observed_until"].replace("Z", "+00:00")
    with pytest.raises(drill.DrillError, match="RFC3339"):
        drill._evidence_passes(plan, gate, evidence)


def test_gate_evidence_rejects_boolean_integer_confusion_and_unknown_operator(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    gate = next(
        action
        for action in plan["actions"]
        if action["type"] == "gate"
        and any(isinstance(check["value"], bool) for check in action["checks"])
    )
    evidence = gate_evidence(plan, gate)
    boolean = next(check for check in gate["checks"] if isinstance(check["value"], bool))
    evidence["checks"][boolean["metric"]]["value"] = int(boolean["value"])
    with pytest.raises(drill.DrillError, match="type"):
        drill._evidence_passes(plan, gate, evidence)
    changed_gate = json.loads(json.dumps(gate))
    changed = next(
        check for check in changed_gate["checks"] if check["metric"] == boolean["metric"]
    )
    changed["operator"] = "contains"
    with pytest.raises(drill.DrillError, match="operator"):
        drill._evidence_passes(plan, changed_gate, gate_evidence(plan, changed_gate))


@pytest.mark.parametrize("value", [True, [1], {"value": 1}, float("nan"), float("inf")])
def test_gate_evidence_rejects_wrong_numeric_types(tmp_path, value):
    plan = drill.build_plan(preflight(tmp_path))
    gate = next(
        action
        for action in plan["actions"]
        if action["type"] == "gate"
        and any(
            isinstance(check["value"], (int, float)) and not isinstance(check["value"], bool)
            for check in action["checks"]
        )
    )
    evidence = gate_evidence(plan, gate)
    metric = next(
        check["metric"]
        for check in gate["checks"]
        if isinstance(check["value"], (int, float)) and not isinstance(check["value"], bool)
    )
    evidence["checks"][metric]["value"] = value
    with pytest.raises(drill.DrillError, match="type|finite"):
        drill._evidence_passes(plan, gate, evidence)


def test_gate_evidence_file_must_be_private_regular_and_bounded(tmp_path):
    relative = Path("gate.json")
    with pytest.raises(drill.DrillError, match="absolute"):
        drill._read_gate_evidence(relative)
    repository_file = drill.ROOT / ".gate-test.json"
    repository_file.write_text("{}")
    try:
        with pytest.raises(drill.DrillError, match="outside"):
            drill._read_gate_evidence(repository_file)
    finally:
        repository_file.unlink()
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * (drill.GATE_EVIDENCE_MAX_BYTES + 1))
    with pytest.raises(drill.DrillError, match="size"):
        drill._read_gate_evidence(oversized)
    with pytest.raises(drill.DrillError, match="read"):
        drill._read_gate_evidence(tmp_path / "missing.json")
    with pytest.raises(drill.DrillError, match="regular"):
        drill._read_gate_evidence(tmp_path)


@pytest.mark.parametrize("mode", drill.MODES)
def test_exactly_one_mutation_resume_and_rollback_for_each_mode(tmp_path, mode):
    plan = drill.build_plan(preflight(tmp_path, mode=mode))
    parsed = execution_files(tmp_path, plan)
    parsed.execute_stage = "marker"
    drill.execute_operation(parsed, execution_runner(plan, []))
    marker = {
        "metadata": {
            "labels": {
                "sugarkube.dev/run-id": plan["run_id"],
                "sugarkube.dev/plan-digest": plan["plan_digest"],
            }
        },
        "data": {"run-id": plan["run_id"], "plan-digest": plan["plan_digest"]},
    }
    stage = plan["actions"][0]
    parsed.execute_stage = stage["id"]
    calls = []
    runner = execution_runner(plan, calls, marker)
    assert drill.execute_operation(parsed, runner)["status"] == "completed"
    assert sum("label" in command or "set" in command for command in calls) == 1
    calls.clear()
    assert drill.execute_operation(parsed, runner)["status"] == "already-completed"
    assert not any("label" in command or "set" in command for command in calls)

    parsed.execute_stage = None
    parsed.rollback_stage = stage["id"]
    calls.clear()
    assert drill.execute_operation(parsed, runner)["status"] == "rolled-back"
    assert any(stage["inverse"][-2:] == call[-2:] for call in calls)


@pytest.mark.parametrize("mode", drill.MODES)
def test_cleanup_deletes_only_exact_marker_and_is_idempotent(tmp_path, mode):
    plan = drill.build_plan(preflight(tmp_path, mode=mode))
    parsed = execution_files(tmp_path, plan)
    parsed.cleanup = True
    drill._record_phase(parsed.journal, plan, "execute", "marker", "intent")
    drill._record_phase(parsed.journal, plan, "execute", "marker", "completed")
    marker = {
        "metadata": {
            "labels": {
                "sugarkube.dev/run-id": plan["run_id"],
                "sugarkube.dev/plan-digest": plan["plan_digest"],
            }
        },
        "data": {"run-id": plan["run_id"], "plan-digest": plan["plan_digest"]},
    }
    calls = []
    assert drill.execute_operation(parsed, execution_runner(plan, calls, marker))["status"] == (
        "clean"
    )
    deletes = [command for command in calls if "delete" in command]
    assert len(deletes) == 1
    assert deletes[0][-1] == drill._marker_name(plan)
    assert "--selector" not in deletes[0]

    # Model the exact resource as absent after deletion; cleanup performs no mutation.
    calls.clear()
    assert drill.execute_operation(parsed, execution_runner(plan, calls))["status"] == (
        "already-clean"
    )
    assert not any("delete" in command for command in calls)


def test_marker_mutation_is_reconciled_after_completion_record_failure(tmp_path, monkeypatch):
    plan = drill.build_plan(preflight(tmp_path))
    parsed = execution_files(tmp_path, plan)
    parsed.execute_stage = "marker"
    runner = execution_runner(plan, [])
    original = drill._append_journal
    count = 0

    def fail_completion(directory, immutable_plan, record):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("injected publication failure")
        original(directory, immutable_plan, record)

    monkeypatch.setattr(drill, "_append_journal", fail_completion)
    with pytest.raises(OSError, match="injected"):
        drill.execute_operation(parsed, runner)
    monkeypatch.setattr(drill, "_append_journal", original)
    assert drill.execute_operation(parsed, runner) == {"status": "completed", "stage": "marker"}


@pytest.mark.parametrize("mode", drill.MODES)
def test_forward_mutation_is_reconciled_without_replay(tmp_path, monkeypatch, mode):
    plan = drill.build_plan(preflight(tmp_path, mode=mode))
    parsed = execution_files(tmp_path, plan)
    runner_calls = []
    runner = execution_runner(plan, runner_calls)
    parsed.execute_stage = "marker"
    drill.execute_operation(parsed, runner)
    parsed.execute_stage = plan["actions"][0]["id"]
    original = drill._append_journal
    count = 0

    def fail_completion(directory, immutable_plan, record):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("injected publication failure")
        original(directory, immutable_plan, record)

    monkeypatch.setattr(drill, "_append_journal", fail_completion)
    with pytest.raises(OSError, match="injected"):
        drill.execute_operation(parsed, runner)
    mutation_count = sum("label" in call or "set" in call for call in runner_calls)
    monkeypatch.setattr(drill, "_append_journal", original)
    assert drill.execute_operation(parsed, runner)["status"] == "completed"
    assert sum("label" in call or "set" in call for call in runner_calls) == mutation_count


def test_journal_gap_duplicate_and_concurrent_execution_are_refused(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    parsed = execution_files(tmp_path, plan)
    payload = {
        "schema_version": 1,
        "run_id": plan["run_id"],
        "plan_digest": plan["plan_digest"],
        "sequence": 1,
        "operation": "execute",
        "stage": "marker",
        "phase": "intent",
    }
    (parsed.journal / "record-0001.json").write_text(json.dumps(payload))
    with pytest.raises(drill.DrillError, match="gap"):
        drill._journal_records(parsed.journal, plan)
    (parsed.journal / "record-0001.json").unlink()
    drill._record_phase(parsed.journal, plan, "execute", "marker", "intent")
    payload["sequence"] = 1
    (parsed.journal / "record-0001.json").write_text(json.dumps(payload))
    with pytest.raises(drill.DrillError, match="duplicate"):
        drill._journal_records(parsed.journal, plan)
    for path in parsed.journal.glob("record-*.json"):
        path.unlink()
    parsed.execute_stage = "marker"
    with drill._execution_lock(parsed.journal):
        with pytest.raises(drill.DrillError, match="another invocation"):
            drill.execute_operation(parsed, execution_runner(plan, []))


def test_marker_lookup_error_is_not_treated_as_absence(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    parsed = execution_files(tmp_path, plan)
    parsed.execute_stage = "marker"
    base = execution_runner(plan, [])

    def failing_lookup(command):
        if "configmap" in command and "get" in command:
            return subprocess.CompletedProcess(command, 1, "", "forbidden")
        return base(command)

    with pytest.raises(drill.DrillError, match="lookup failed"):
        drill.execute_operation(parsed, failing_lookup)


def test_stage_preflight_requires_stage_specific_image(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    parsed = execution_files(tmp_path, plan)
    replacement = plan["expected_deployment"]["replacement_image"]
    current = plan["expected_deployment"]["current_image"]
    runner = execution_runner(plan, [], initial_image=replacement)
    with pytest.raises(drill.DrillError, match="coordinates drifted"):
        drill._assert_stage_preflight(plan, parsed.kubeconfig, runner, current)
    drill._assert_stage_preflight(plan, parsed.kubeconfig, runner, replacement)


@pytest.mark.parametrize("mode", drill.MODES)
def test_partial_run_can_rollback_and_cleanup(tmp_path, mode):
    plan = drill.build_plan(preflight(tmp_path, mode=mode))
    parsed = execution_files(tmp_path, plan)
    runner = execution_runner(plan, [])
    parsed.execute_stage = "marker"
    drill.execute_operation(parsed, runner)
    stage = plan["actions"][0]
    parsed.execute_stage = stage["id"]
    drill.execute_operation(parsed, runner)
    parsed.execute_stage = None
    parsed.rollback_stage = stage["id"]
    drill.execute_operation(parsed, runner)
    parsed.rollback_stage = None
    parsed.cleanup = True
    assert drill.execute_operation(parsed, runner)["status"] == "clean"
    parsed.cleanup = False
    parsed.execute_stage = plan["actions"][1]["id"]
    with pytest.raises(drill.DrillError, match="after rollback"):
        drill.execute_operation(parsed, runner)


def _journal_through(parsed, plan, stage_id, *, pending_operation="execute", pending_metadata=None):
    drill._record_phase(parsed.journal, plan, "execute", "marker", "intent")
    drill._record_phase(parsed.journal, plan, "execute", "marker", "completed")
    for action in plan["actions"]:
        if action["id"] == stage_id:
            drill._record_phase(
                parsed.journal,
                plan,
                pending_operation,
                stage_id,
                "intent",
                **(pending_metadata or {}),
            )
            return action
        drill._record_phase(parsed.journal, plan, "execute", action["id"], "intent")
        drill._record_phase(parsed.journal, plan, "execute", action["id"], "completed")
    raise AssertionError(f"missing stage {stage_id}")


@pytest.mark.parametrize(
    ("operation", "initial_image", "expected_status"),
    [
        ("execute", "replacement_image", "completed"),
        ("rollback", "current_image", "rolled-back"),
    ],
)
def test_interrupted_replace_post_state_reconciles_without_replay(
    tmp_path, operation, initial_image, expected_status
):
    plan = drill.build_plan(preflight(tmp_path))
    parsed = execution_files(tmp_path, plan)
    action = _journal_through(parsed, plan, "replace")
    if operation == "rollback":
        # A rollback intent follows the completed forward operation.
        drill._record_phase(parsed.journal, plan, "execute", "replace", "completed")
        drill._record_phase(parsed.journal, plan, "rollback", "replace", "intent")
    parsed.execute_stage = "replace" if operation == "execute" else None
    parsed.rollback_stage = "replace" if operation == "rollback" else None
    marker = {"data": {"run-id": plan["run_id"], "plan-digest": plan["plan_digest"]}}
    calls = []
    runner = execution_runner(plan, calls, marker, plan["expected_deployment"][initial_image])

    assert drill.execute_operation(parsed, runner)["status"] == expected_status
    mutation = action["command"] if operation == "execute" else action["inverse"]
    assert not any(call[-2:] == mutation[-2:] for call in calls)


@pytest.mark.parametrize("operation", ["execute", "rollback"])
def test_pending_replace_pre_state_retries_once_and_verifies(tmp_path, operation):
    plan = drill.build_plan(preflight(tmp_path))
    parsed = execution_files(tmp_path, plan)
    if operation == "execute":
        action = _journal_through(parsed, plan, "replace")
        parsed.execute_stage = "replace"
        initial = plan["expected_deployment"]["current_image"]
        command = action["command"]
    else:
        _journal_through(parsed, plan, "replace")
        # Complete the pending forward replace before beginning its rollback.
        drill._record_phase(parsed.journal, plan, "execute", "replace", "completed")
        drill._record_phase(parsed.journal, plan, "rollback", "replace", "intent")
        action = next(item for item in plan["actions"] if item["id"] == "replace")
        parsed.rollback_stage = "replace"
        initial = plan["expected_deployment"]["replacement_image"]
        command = action["inverse"]
    marker = {"data": {"run-id": plan["run_id"], "plan-digest": plan["plan_digest"]}}
    calls = []
    drill.execute_operation(parsed, execution_runner(plan, calls, marker, initial))
    assert sum(call[-2:] == command[-2:] for call in calls) == 1
    assert sum("deployment" in call and "get" in call for call in calls) >= 2


@pytest.mark.parametrize("operation", ["execute", "rollback"])
def test_pending_replace_rejects_third_image(tmp_path, operation):
    plan = drill.build_plan(preflight(tmp_path))
    parsed = execution_files(tmp_path, plan)
    _journal_through(parsed, plan, "replace")
    if operation == "execute":
        parsed.execute_stage = "replace"
    else:
        drill._record_phase(parsed.journal, plan, "execute", "replace", "completed")
        drill._record_phase(parsed.journal, plan, "rollback", "replace", "intent")
        parsed.rollback_stage = "replace"
    marker = {"data": {"run-id": plan["run_id"], "plan-digest": plan["plan_digest"]}}
    with pytest.raises(drill.DrillError, match="coordinates drifted"):
        drill.execute_operation(
            parsed,
            execution_runner(plan, [], marker, "registry.example/relay@sha256:" + "d" * 64),
        )


def test_pending_gate_revalidates_evidence_without_mutation(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    gate = next(item for item in plan["actions"] if item["type"] == "gate")
    parsed = execution_files(tmp_path, plan)
    parsed.execute_stage = gate["id"]
    parsed.gate_evidence = tmp_path / "gate.json"
    payload = json.dumps(gate_evidence(plan, gate)).encode()
    parsed.gate_evidence.write_bytes(payload)
    summary = drill._evidence_passes(plan, gate, json.loads(payload), now=None)[1]
    _journal_through(
        parsed,
        plan,
        gate["id"],
        pending_metadata={
            "evidence_digest": drill.hashlib.sha256(payload).hexdigest(),
            "evidence_summary": summary,
        },
    )
    marker = {"data": {"run-id": plan["run_id"], "plan-digest": plan["plan_digest"]}}
    calls = []
    assert (
        drill.execute_operation(
            parsed,
            execution_runner(plan, calls, marker, plan["expected_deployment"]["replacement_image"]),
        )["status"]
        == "completed"
    )
    assert not any("label" in call or "set" in call for call in calls)
    records = drill._journal_records(parsed.journal, plan)
    assert records[-1]["evidence_digest"] == drill.hashlib.sha256(payload).hexdigest()
    assert set(records[-1]["evidence_summary"]) == {
        "observed_from",
        "observed_until",
        "sources",
    }


def test_pending_gate_refuses_changed_evidence_digest(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    gate = next(item for item in plan["actions"] if item["type"] == "gate")
    parsed = execution_files(tmp_path, plan)
    parsed.execute_stage = gate["id"]
    parsed.gate_evidence = tmp_path / "gate.json"
    original = json.dumps(gate_evidence(plan, gate)).encode()
    parsed.gate_evidence.write_bytes(original)
    summary = drill._evidence_passes(plan, gate, json.loads(original), now=None)[1]
    _journal_through(
        parsed,
        plan,
        gate["id"],
        pending_metadata={
            "evidence_digest": drill.hashlib.sha256(original).hexdigest(),
            "evidence_summary": summary,
        },
    )
    parsed.gate_evidence.write_text(json.dumps(gate_evidence(plan, gate), indent=2))
    marker = {"data": {"run-id": plan["run_id"], "plan-digest": plan["plan_digest"]}}
    with pytest.raises(drill.DrillError, match="digest changed while still fresh"):
        drill.execute_operation(
            parsed,
            execution_runner(plan, [], marker, plan["expected_deployment"]["replacement_image"]),
        )


def test_fresh_evidence_recovers_expired_pending_gate_without_mutation(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    gate = next(item for item in plan["actions"] if item["type"] == "gate")
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    old = gate_evidence(plan, gate, now - timedelta(minutes=6))
    old_payload = json.dumps(old).encode()
    old_summary = drill._evidence_passes(plan, gate, old, now - timedelta(minutes=6))[1]
    parsed = execution_files(tmp_path, plan)
    parsed.execute_stage = gate["id"]
    parsed.gate_evidence = tmp_path / "replacement-gate.json"
    parsed.gate_evidence.write_text(json.dumps(gate_evidence(plan, gate, now)))
    _journal_through(
        parsed,
        plan,
        gate["id"],
        pending_metadata={
            "evidence_digest": drill.hashlib.sha256(old_payload).hexdigest(),
            "evidence_summary": old_summary,
        },
    )
    calls = []
    result = drill.execute_operation(
        parsed,
        execution_runner(
            plan,
            calls,
            _matching_marker(plan),
            plan["expected_deployment"]["replacement_image"],
        ),
        now,
    )
    assert result["status"] == "completed"
    records = drill._journal_records(parsed.journal, plan)
    assert [record["phase"] for record in records[-2:]] == ["expired", "completed"]
    assert records[-2]["evidence_digest"] == drill.hashlib.sha256(old_payload).hexdigest()
    assert not any("label" in call or "set" in call for call in calls)


def _matching_marker(plan):
    return {"data": {"run-id": plan["run_id"], "plan-digest": plan["plan_digest"]}}


def test_marker_success_without_post_state_refuses_completion(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    parsed = execution_files(tmp_path, plan)
    parsed.execute_stage = "marker"
    base = execution_runner(plan, [])

    def false_success(command):
        if "configmap" in command and "create" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        return base(command)

    with pytest.raises(drill.DrillError, match="marker is missing"):
        drill.execute_operation(parsed, false_success)
    assert drill._pending_operation(drill._journal_records(parsed.journal, plan)) == (
        "execute",
        "marker",
    )


def test_action_success_without_post_state_refuses_completion(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    parsed = execution_files(tmp_path, plan)
    drill._record_phase(parsed.journal, plan, "execute", "marker", "intent")
    drill._record_phase(parsed.journal, plan, "execute", "marker", "completed")
    action = plan["actions"][0]
    parsed.execute_stage = action["id"]
    base = execution_runner(plan, [], _matching_marker(plan))

    def false_success(command):
        if command[-2:] == action["command"][-2:]:
            return subprocess.CompletedProcess(command, 0, "", "")
        return base(command)

    with pytest.raises(drill.DrillError, match="post-state"):
        drill.execute_operation(parsed, false_success)
    assert drill._pending_operation(drill._journal_records(parsed.journal, plan)) == (
        "execute",
        action["id"],
    )


def test_rollback_success_without_post_state_refuses_completion(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    parsed = execution_files(tmp_path, plan)
    action = _journal_through(parsed, plan, "replace")
    drill._record_phase(parsed.journal, plan, "execute", "replace", "completed")
    parsed.rollback_stage = "replace"
    base = execution_runner(
        plan, [], _matching_marker(plan), plan["expected_deployment"]["replacement_image"]
    )

    def false_success(command):
        if command[-2:] == action["inverse"][-2:]:
            return subprocess.CompletedProcess(command, 0, "", "")
        return base(command)

    with pytest.raises(drill.DrillError, match="rollback post-state"):
        drill.execute_operation(parsed, false_success)
    assert drill._pending_operation(drill._journal_records(parsed.journal, plan)) == (
        "rollback",
        "replace",
    )


def test_marker_delete_success_without_absence_refuses_completion(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    parsed = execution_files(tmp_path, plan)
    parsed.cleanup = True
    drill._record_phase(parsed.journal, plan, "execute", "marker", "intent")
    drill._record_phase(parsed.journal, plan, "execute", "marker", "completed")
    base = execution_runner(plan, [], _matching_marker(plan))

    def false_success(command):
        if "configmap" in command and "delete" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        return base(command)

    with pytest.raises(drill.DrillError, match="cleanup post-state"):
        drill.execute_operation(parsed, false_success)
    assert drill._pending_operation(drill._journal_records(parsed.journal, plan)) == (
        "cleanup",
        "cleanup",
    )


def test_action_post_state_lookup_error_remains_pending(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    parsed = execution_files(tmp_path, plan)
    drill._record_phase(parsed.journal, plan, "execute", "marker", "intent")
    drill._record_phase(parsed.journal, plan, "execute", "marker", "completed")
    action = plan["actions"][0]
    parsed.execute_stage = action["id"]
    base = execution_runner(plan, [], _matching_marker(plan))
    lookups = 0

    def fail_post_lookup(command):
        nonlocal lookups
        if "get" in command and (
            "deployment" in command or action["resource"].split("/")[0] in command
        ):
            lookups += 1
            if lookups >= 3:
                return subprocess.CompletedProcess(command, 1, "", "unavailable")
        return base(command)

    with pytest.raises(drill.DrillError, match="state lookup failed"):
        drill.execute_operation(parsed, fail_post_lookup)
    assert drill._pending_operation(drill._journal_records(parsed.journal, plan)) == (
        "execute",
        action["id"],
    )


@pytest.mark.parametrize(
    "change,message",
    [
        ({"schema_version": 1}, "schema"),
        ({"environment": "prod"}, "staging"),
        ({"run_id": "unsafe_name"}, "run ID"),
        ({"plan_digest": "bad"}, "digest"),
        ({"actions": []}, "ordered stages"),
        ({"actions": [{"id": "duplicate"}, {"id": "duplicate"}]}, "ambiguous"),
        ({"actions": [{"id": "stage", "command": "echo unsafe"}]}, "shell-string"),
    ],
)
def test_execution_plan_loader_rejects_malformed_contracts(tmp_path, change, message):
    plan = drill.build_plan(preflight(tmp_path))
    plan.update(change)
    if "plan_digest" not in change:
        plan["plan_digest"] = drill._plan_digest(plan)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))

    with pytest.raises(drill.DrillError, match=message):
        drill._load_execution_plan(path)


def test_execution_plan_loader_rejects_unreadable_and_invalid_json(tmp_path):
    with pytest.raises(drill.DrillError, match="cannot be read"):
        drill._load_execution_plan(tmp_path / "missing.json")
    path = tmp_path / "plan.json"
    path.write_text("not-json")
    with pytest.raises(drill.DrillError, match="cannot be read"):
        drill._load_execution_plan(path)


def test_private_directory_and_command_guards_fail_closed(tmp_path):
    with pytest.raises(drill.DrillError, match="absolute"):
        drill._private_directory(Path("relative"), "journal")
    with pytest.raises(drill.DrillError, match="outside"):
        drill._private_directory(drill.ROOT, "journal")
    with pytest.raises(drill.DrillError, match="kubeconfig"):
        drill._bind_command(["kubectl", "get", "pods"], tmp_path / "config")
    with pytest.raises(drill.DrillError, match="shell-string"):
        drill._run_checked(lambda _: None, "unsafe", "failed")
    with pytest.raises(drill.DrillError, match="failed"):
        drill._run_checked(
            lambda command: subprocess.CompletedProcess(command, 1, "", ""),
            ["false"],
            "failed",
        )


def test_main_redacts_snapshot_and_execution_failures(tmp_path, capsys, monkeypatch):
    parsed = args(tmp_path)
    parsed.snapshot.write_text("not-json")
    argv = []
    for name, value in vars(parsed).items():
        option = "--" + name.replace("_", "-")
        if isinstance(value, bool):
            if value:
                argv.append(option)
        else:
            argv.extend((option, str(value)))
    assert drill.main(argv) == 2
    assert str(parsed.snapshot) not in capsys.readouterr().err

    monkeypatch.setattr(
        drill,
        "execute_operation",
        lambda *_: (_ for _ in ()).throw(drill.DrillError("safe refusal")),
    )
    assert (
        drill.main(
            [
                "--execute-stage",
                "replace",
                "--plan",
                str(tmp_path / "plan.json"),
                "--journal",
                str(tmp_path),
                "--kubeconfig",
                str(parsed.kubeconfig),
            ]
        )
        == 2
    )
    assert "safe refusal" in capsys.readouterr().err

    monkeypatch.setattr(drill, "execute_operation", lambda *_: {"status": "completed"})
    assert (
        drill.main(
            [
                "--execute-stage",
                "replace",
                "--plan",
                str(tmp_path / "plan.json"),
                "--journal",
                str(tmp_path),
                "--kubeconfig",
                str(parsed.kubeconfig),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {"status": "completed"}


@pytest.mark.parametrize("stdout", ["", "not-json"])
def test_marker_validation_rejects_missing_or_malformed_marker(tmp_path, stdout):
    plan = drill.build_plan(preflight(tmp_path))
    runner = lambda command: subprocess.CompletedProcess(command, 0, stdout, "")
    with pytest.raises(drill.DrillError, match="missing|malformed"):
        drill._validate_marker(plan, tmp_path / "kubeconfig", runner)


def test_action_matching_rejects_missing_container_and_unknown_state(tmp_path):
    plan = drill.build_plan(preflight(tmp_path))
    action = next(item for item in plan["actions"] if item["id"] == "replace")
    assert not drill._action_matches(plan, action, {}, post=False)
    action = {**action, "old_state": {}}
    assert not drill._action_matches(
        plan,
        action,
        {
            "spec": {
                "template": {
                    "spec": {"containers": [{"name": plan["expected_deployment"]["container"]}]}
                }
            }
        },
        post=False,
    )


@pytest.mark.parametrize("mode", ["metrics-oom", "quota-exhaustion"])
def test_action_prestate_accepts_exact_forward_and_inverse_states(tmp_path, mode):
    plan = drill.build_plan(preflight(tmp_path, mode=mode))
    kubeconfig = tmp_path / "private" / "kubeconfig"

    for action in (item for item in plan["actions"] if item["type"] == "mutation"):
        kind = action["resource"].split("/", 1)[0]

        def observed(inverse=False):
            if kind in {"probe", "servicemonitor"}:
                labels = (
                    {"sugarkube.dev/incident-paused": "true"}
                    if inverse
                    else {
                        "release": action["old_state"]["release"],
                        "sugarkube.dev/incident-paused": action["old_state"].get(
                            "sugarkube.dev/incident-paused"
                        ),
                    }
                )
                return {"metadata": {"labels": labels}}
            state = dict(action["old_state"])
            if inverse:
                if "set" in action["command"] and "image" in action["command"]:
                    state = {"image": plan["expected_deployment"]["replacement_image"]}
                elif "TOKENPLACE_METRICS_MODE=degraded" in action["command"]:
                    state = {"TOKENPLACE_METRICS_MODE": "degraded"}
            container = {
                "name": plan["expected_deployment"]["container"],
                "image": state.get("image", plan["expected_deployment"]["current_image"]),
                "env": (
                    [{"name": "TOKENPLACE_METRICS_MODE", "value": state["TOKENPLACE_METRICS_MODE"]}]
                    if "TOKENPLACE_METRICS_MODE" in state
                    else []
                ),
            }
            return {"spec": {"template": {"spec": {"containers": [container]}}}}

        for inverse in (False, True):
            payload = observed(inverse)
            runner = lambda command, payload=payload: subprocess.CompletedProcess(
                command, 0, json.dumps(payload), ""
            )
            drill._assert_action_prestate(plan, action, kubeconfig, runner, inverse=inverse)
