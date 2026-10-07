"""Offline inventory fixtures exercise the shared application render boundary."""

import copy
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from scripts import app_chart

FIXTURES = Path(__file__).parent / "fixtures/workload_inventory"


def inputs(profile):
    app = "dspace" if profile == "dspace" else "tokenplace"
    chart = {
        "dspace": "oci://ghcr.io/democratizedspace/charts/dspace",
        "relay": "oci://ghcr.io/futuroptimist/charts/tokenplace",
        "local": str(app_chart.REPO_ROOT / "apps/tokenplace-relay"),
    }[profile]
    return app_chart.ReleaseInputs(
        app,
        "staging",
        "dspace" if app == "dspace" else "relay",
        app,
        chart,
        "1.0.0",
        (),
        "main-deadbee",
    )


def documents(profile):
    docs = app_chart.safe_yaml_documents(
        (FIXTURES / f"{'dspace' if profile == 'dspace' else 'relay'}.yaml").read_text()
    )
    if profile == "local":
        for doc in docs:
            doc["metadata"]["name"] = "relay-tokenplace-relay"
    return docs


@pytest.mark.parametrize("profile", ["dspace", "relay", "local"])
@pytest.mark.parametrize("replicas", [None, 0, 1, 2, 5])
def test_positive_inventory_preserves_replica_semantics(profile, replicas):
    docs = documents(profile)
    if replicas is None:
        del docs[0]["spec"]["replicas"]
    else:
        docs[0]["spec"]["replicas"] = replicas
    assert app_chart.validate_workload_inventory(docs, inputs(profile)) == []


@pytest.mark.parametrize("profile", ["dspace", "relay", "local"])
@pytest.mark.parametrize(
    "mutation",
    [
        "sidecar",
        "init",
        "ephemeral",
        "image",
        "container",
        "tag",
        "duplicate",
        "namespace",
        "pod_namespace",
        "release_namespace",
        "release",
        "selector",
        "service_selector",
        "hook",
        "missing",
        "api",
        "null_namespace",
    ],
)
def test_negative_inventory(profile, mutation):
    docs = documents(profile)
    deployment = docs[0]
    pod = deployment["spec"]["template"]
    containers = pod["spec"]["containers"]
    if mutation == "sidecar":
        containers.append(copy.deepcopy(containers[0]))
    elif mutation in {"init", "ephemeral"}:
        pod["spec"][mutation + "Containers"] = copy.deepcopy(containers)
    elif mutation == "image":
        containers[0]["image"] = "attacker/image:main-deadbee"
    elif mutation == "container":
        containers[0]["name"] = "other"
    elif mutation == "tag":
        containers[0]["image"] += "-other"
    elif mutation == "duplicate":
        extra = copy.deepcopy(deployment)
        extra["metadata"]["name"] = "unrelated"
        docs.append(extra)
    elif mutation in {"namespace", "null_namespace"}:
        deployment["metadata"]["namespace"] = None if mutation == "null_namespace" else "other"
    elif mutation == "pod_namespace":
        pod["metadata"]["namespace"] = "other"
    elif mutation == "release_namespace":
        deployment["metadata"]["annotations"] = {"meta.helm.sh/release-namespace": "other"}
    elif mutation == "release":
        deployment["metadata"]["labels"]["app.kubernetes.io/instance"] = "other"
    elif mutation == "selector":
        pod["metadata"]["labels"] = {"app": "other"}
    elif mutation == "service_selector":
        docs[1]["spec"]["selector"] = {"app": "other"}
    elif mutation == "hook":
        deployment["metadata"]["annotations"] = {"helm.sh/hook": "pre-install"}
    elif mutation == "missing":
        docs.pop(0)
    elif mutation == "api":
        deployment["apiVersion"] = "other/v1"
    assert app_chart.validate_workload_inventory(docs, inputs(profile))


@pytest.mark.parametrize(
    "kind",
    [
        "Pod",
        "Job",
        "CronJob",
        "StatefulSet",
        "DaemonSet",
        "ReplicaSet",
        "List",
        "Secret",
        "Namespace",
        "CustomWorkload",
    ],
)
@pytest.mark.parametrize("profile", ["dspace", "relay", "local"])
def test_unexpected_resources_are_rejected_even_without_release_labels(kind, profile):
    docs = documents(profile)
    docs.append({"apiVersion": "v1", "kind": kind, "metadata": {"name": "extra"}})
    assert app_chart.validate_workload_inventory(docs, inputs(profile))


def test_archive_binding_and_digest_qualified_coordinate(tmp_path):
    original = inputs("dspace")
    archive = tmp_path / "chart.tgz"
    archive.write_bytes(b"offline archive fixture")
    bound = replace(
        original,
        chart=str(archive),
        chart_origin=original.chart,
        chart_archive_digest="sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest(),
    )
    assert app_chart.validate_workload_inventory(documents("dspace"), bound) == []
    archive.write_bytes(b"changed")
    assert app_chart.validate_workload_inventory(documents("dspace"), bound)
    assert (
        app_chart.validate_workload_inventory(
            documents("dspace"), replace(original, chart=original.chart + "@sha256:" + "a" * 64)
        )
        == []
    )


def test_unrelated_external_chart_does_not_inherit_application_profile():
    original = inputs("dspace")
    assert (
        app_chart.validate_workload_inventory(
            [{"kind": "Job"}], replace(original, chart="oci://example/charts/other")
        )
        == []
    )


def test_shared_render_validator_enforces_inventory():
    manifest = (FIXTURES / "relay.yaml").read_text()
    assert app_chart.validate_rendered_manifest(manifest, inputs("relay")) == []
    errors = app_chart.validate_rendered_manifest(
        manifest + "\n---\nkind: Pod\nmetadata:\n  name: extra\n", inputs("relay")
    )
    assert any("inventory: unexpected resource kind" in error for error in errors)


@pytest.mark.parametrize("selector", [{"any": True}, {"matchNames": ["other"]}])
def test_monitor_cannot_select_another_namespace(selector):
    docs = documents("dspace")
    docs.append(
        {
            "apiVersion": "monitoring.coreos.com/v1",
            "kind": "ServiceMonitor",
            "metadata": copy.deepcopy(docs[1]["metadata"]),
            "spec": {
                "namespaceSelector": selector,
                "selector": {"matchLabels": docs[1]["metadata"]["labels"]},
            },
        }
    )
    assert any(
        "namespace selector conflict" in error
        for error in app_chart.validate_workload_inventory(docs, inputs("dspace"))
    )


def test_duplicate_yaml_keys_cannot_hide_an_extra_container():
    with pytest.raises(ValueError, match="duplicate YAML mapping key"):
        app_chart.safe_yaml_documents("spec:\n  containers: []\n  containers: []\n")


@pytest.mark.parametrize("profile", ["dspace", "relay", "local"])
def test_primary_name_cannot_be_replaced_with_an_unrelated_workload(profile):
    docs = documents(profile)
    docs[0]["metadata"]["name"] = "unexpected"
    assert any(
        "name mismatch" in error
        for error in app_chart.validate_workload_inventory(docs, inputs(profile))
    )


def test_profile_cannot_be_selected_for_a_different_application():
    assert app_chart.validate_workload_inventory(
        documents("dspace"), replace(inputs("dspace"), app="other")
    )


def test_legacy_test_pod_is_not_enabled_by_the_published_profile():
    docs = documents("dspace")
    docs.append(
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": "dspace-test-connection", "annotations": {"helm.sh/hook": "test"}},
            "spec": {"containers": [{"name": "wget", "image": "busybox:1.36"}]},
        }
    )
    assert app_chart.validate_workload_inventory(docs, inputs("dspace"))


def test_published_dspace_source_render_fixture():
    """charts/dspace at 22f506e, staging values and image tag main-deadbee."""
    original = inputs("dspace")
    manifest = (FIXTURES / "dspace-published.yaml").read_text()
    assert app_chart.validate_rendered_manifest(manifest, original) == []


def test_local_relay_chart_render_matches_profile():
    import shutil
    import subprocess

    if not shutil.which("helm"):
        # TODO: Run this offline chart integration check wherever Helm is available.
        # Root cause: Helm is not installed in every Python-only test environment.
        # Estimated fix: Install Helm locally or in CI and rerun this test.
        pytest.skip("Helm is required for the local chart render test")
    original = replace(inputs("local"), release="tokenplace", namespace="tokenplace")
    command = original.helm_template_command() + [
        "--set",
        "image.repository=ghcr.io/futuroptimist/tokenplace-relay",
    ]
    manifest = subprocess.run(command, check=True, text=True, capture_output=True).stdout
    assert app_chart.validate_rendered_manifest(manifest, original) == []
