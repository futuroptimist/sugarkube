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
        if key in {"acknowledge_state_loss", "dry_run"}:
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
        if key in {"acknowledge_state_loss", "dry_run"}:
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
    passing = {check["metric"]: check["value"] for check in gate["checks"]}
    assert drill._evidence_passes(gate, passing) is True
    failing = dict(passing)
    failing[gate["checks"][0]["metric"]] = -1
    assert drill._evidence_passes(gate, failing) is False
    with pytest.raises(drill.DrillError, match="incomplete"):
        drill._evidence_passes(gate, {})


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
    assert stage["inverse"][-2:] == calls[-1][-2:]


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
