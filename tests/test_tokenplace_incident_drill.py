import argparse
from pathlib import Path

import pytest

from scripts import tokenplace_incident_drill as drill


def args(tmp_path: Path, **changes):
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("safe fixture")
    values = dict(
        mode="metrics-oom",
        host="staging.token.place",
        kubeconfig=kubeconfig,
        context="sugar-staging",
        environment="staging",
        namespace="tokenplace",
        deployment="tokenplace",
        container="relay",
        image="registry.example/relay@sha256:" + "a" * 64,
        previous_image="registry.example/relay@sha256:" + "b" * 64,
        replicas=1,
        memory_limit="512Mi",
        service_monitor="tokenplace",
        run_id="drill-test",
        evidence=Path("evidence/drill-test.json"),
        acknowledge_state_loss=True,
        dry_run=True,
    )
    values.update(changes)
    return argparse.Namespace(**values)


@pytest.mark.parametrize(
    "change",
    [
        {"environment": "prod"},
        {"context": "sugar-prod"},
        {"host": "token.place"},
        {"replicas": 0},
        {"image": "registry.example/relay:latest"},
        {"previous_image": "registry.example/relay:latest"},
        {"memory_limit": "unknown"},
        {"acknowledge_state_loss": False},
        {"service_monitor": ""},
    ],
)
def test_preconditions_fail_closed_before_plan(tmp_path, change):
    with pytest.raises(drill.DrillError):
        drill.validate(args(tmp_path, **change))


def test_metrics_oom_pauses_only_metrics_and_restores_ordered(tmp_path):
    plan = drill.build_plan(
        "metrics-oom", drill.validate(args(tmp_path)), drill.inventory("staging")
    )
    pauses = [a["resource"] for a in plan["actions"] if a["stage"] == "pause"]
    assert pauses == ["servicemonitor/tokenplace"]
    assert plan["preserved"] == [
        "probe/blackbox-tokenplace-staging-livez",
        "probe/blackbox-tokenplace-staging-healthz",
    ]
    stages = [a["stage"] for a in plan["actions"]]
    assert stages.index("compute-registration") < stages.index("restore-root")
    assert stages.index("restore-root") < stages.index("restore-metadata")
    assert stages.index("restore-metadata") < stages.index("restore-metrics-last")
    assert all(
        action["rollback"]
        for action in plan["actions"]
        if action["stage"]
        in {"pause", "replace", "restore-root", "restore-metadata", "restore-metrics-last"}
        and action["command"][0] == "kubectl"
    )
    probe_mutations = [
        a
        for a in plan["actions"]
        if a["resource"].startswith("probe/") and a["command"][0] == "kubectl"
    ]
    assert probe_mutations == []


def test_quota_mode_pauses_exact_public_information_probes(tmp_path):
    plan = drill.build_plan(
        "quota-exhaustion", drill.validate(args(tmp_path)), drill.inventory("staging")
    )
    assert [a["resource"] for a in plan["actions"] if a["stage"] == "pause"] == [
        "probe/blackbox-tokenplace-staging-root",
        "probe/blackbox-tokenplace-staging-metadata",
    ]
    rendered = str(plan)
    assert "incident-paused=true" not in " ".join(plan["preserved"])
    assert "staging.token.place" not in rendered
    assert all(
        action["command"][1:3] == ["--kubeconfig", str((tmp_path / "kubeconfig").resolve())]
        for action in plan["actions"]
        if action["command"][0] == "kubectl"
    )
    assert not any(
        a["command"][0] == "kubectl" and a["resource"].startswith("servicemonitor/")
        for a in plan["actions"]
    )


def test_inventory_has_exact_route_and_method_contract():
    selected = drill.inventory("staging")
    assert (selected["root"]["route"], selected["root"]["method"]) == ("/", "GET")
    assert (selected["metadata"]["route"], selected["metadata"]["method"]) == (
        "/api/v1/meta",
        "GET",
    )


def test_duplicate_inventory_route_classes_are_rejected(monkeypatch):
    contract = drill.yaml.safe_load(
        (drill.ROOT / "config/observability/probe-quotas.yaml").read_text()
    )
    duplicate = next(
        item
        for item in contract["probes"]
        if item["application"] == "tokenplace" and item["environment"] == "staging"
    ).copy()
    contract["probes"].append(duplicate)
    monkeypatch.setattr(drill.yaml, "safe_load", lambda _: contract)
    with pytest.raises(drill.DrillError, match="duplicate route classes"):
        drill.inventory("staging")


def test_plan_records_identity_and_executable_image_rollback(tmp_path):
    coordinates = drill.validate(args(tmp_path, replicas=2, memory_limit="1Gi"))
    plan = drill.build_plan("metrics-oom", coordinates, drill.inventory("staging"))
    assert plan["expected_deployment"] == {
        "replicas": 2,
        "container": "relay",
        "image": "registry.example/relay@sha256:" + "a" * 64,
        "memory_limit": "1Gi",
    }
    replace = next(action for action in plan["actions"] if action["stage"] == "replace")
    assert replace["rollback"][-1].endswith("=" + coordinates.previous_image)
    assert any(a["stage"] == "verify-deployment-identity" for a in plan["actions"])
    assert plan["state_changes"]["repository"] is True


def test_absolute_repository_evidence_path_is_accepted(tmp_path):
    evidence = drill.ROOT / "evidence" / "absolute-test.json"
    coordinates = drill.validate(args(tmp_path, evidence=evidence))
    assert coordinates.run_id == "drill-test"


def test_relative_evidence_path_is_anchored_to_repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    coordinates_args = args(tmp_path)
    drill.validate(coordinates_args)
    assert coordinates_args.evidence == drill.ROOT / "evidence" / "drill-test.json"


def test_container_restart_and_pod_replacement_semantics_are_machine_visible():
    text = (drill.ROOT / "docs/tokenplace-incident-runbooks.md").read_text()
    assert "container restart preserves" in text
    assert "Pod replacement deletes" in text
    assert "pod-lifetime `emptyDir`" in text
