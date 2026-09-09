import argparse
from pathlib import Path

import pytest

from scripts import tokenplace_incident_drill as drill


def args(tmp_path: Path, **changes):
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("safe fixture")
    values = dict(
        mode="metrics-oom",
        host="staging.example",
        kubeconfig=kubeconfig,
        context="sugar-staging",
        environment="staging",
        namespace="tokenplace",
        deployment="tokenplace",
        container="relay",
        image="registry.example/relay@sha256:" + "a" * 64,
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
        {"replicas": 0},
        {"image": "registry.example/relay:latest"},
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
    assert "staging.example" not in rendered and str(tmp_path) not in rendered
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


def test_container_restart_and_pod_replacement_semantics_are_machine_visible():
    text = (drill.ROOT / "docs/tokenplace-incident-runbooks.md").read_text()
    assert "container restart preserves" in text
    assert "Pod replacement deletes" in text
    assert "pod-lifetime `emptyDir`" in text
