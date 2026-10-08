"""Offline rendered isolation contract; no Kubernetes client or live requests."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "apps/tokenplace-test-lane"
IMAGE = (
    "ghcr.io/futuroptimist/tokenplace-relay@sha256:"
    "5d761cefc0495926b63da1e0a4119155a005e165e469da90e7f19be0f7fdff8e"
)
SOURCE = "5e190f5c6ff66e9c05934a0e2ce2c1a440b9ea49"


def render(*args, namespace="tokenplace-k243"):
    helm = shutil.which("helm")
    if not helm:
        # TODO: Provide Helm on hosts running this optional rendering suite.
        # Root cause: General Python-only test jobs do not install Helm.
        # Estimated fix: Install Helm 3 locally; dedicated K243 CI already installs it.
        pytest.skip("Helm required for offline rendering")
    return subprocess.run(
        [helm, "template", "k243", str(CHART), "--namespace", namespace, *args],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def objects():
    result = render("--set-string", "runId=offline-fixture")
    assert result.returncode == 0, result.stderr
    return list(yaml.safe_load_all(result.stdout))


def by_kind(objects, kind):
    return [obj for obj in objects if obj["kind"] == kind]


def test_render_is_dedicated_private_and_has_no_serving_service_overlap(objects):
    assert {o["kind"] for o in objects} == {
        "Namespace",
        "ServiceAccount",
        "Deployment",
        "Service",
        "NetworkPolicy",
    }
    for obj in objects:
        assert obj["metadata"]["name"].startswith("tokenplace-k243")
        if obj["kind"] != "Namespace":
            assert obj["metadata"]["namespace"] == "tokenplace-k243"
    (service,) = by_kind(objects, "Service")
    assert service["spec"]["type"] == "ClusterIP"
    assert set(service["spec"]) == {"type", "selector", "ports"}
    (deploy,) = by_kind(objects, "Deployment")
    labels = deploy["spec"]["template"]["metadata"]["labels"]
    assert service["spec"]["selector"] == labels
    assert deploy["spec"]["selector"]["matchLabels"] == labels
    assert labels == {
        "app.kubernetes.io/name": "tokenplace-k243-relay",
        "sugarkube.dev/k243-run": "offline-fixture",
    }
    # Serving chart's broad name/instance selectors must not select lane pods.
    assert labels["app.kubernetes.io/name"] not in {"tokenplace", "tokenplace-relay"}
    assert "app.kubernetes.io/instance" not in labels


def test_image_memory_process_and_credential_boundaries(objects):
    (deploy,) = by_kind(objects, "Deployment")
    assert deploy["metadata"]["annotations"]["sugarkube.dev/source-revision"] == SOURCE
    assert deploy["spec"]["replicas"] == 1
    assert deploy["spec"]["strategy"] == {"type": "Recreate"}
    pod = deploy["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["enableServiceLinks"] is False
    assert not any(k in pod for k in ("hostNetwork", "hostPID", "initContainers"))
    (container,) = pod["containers"]
    assert container["image"] == IMAGE
    assert not any(k in container for k in ("envFrom", "command", "args"))
    env = {item["name"]: item["value"] for item in container["env"]}
    assert env == {
        "RELAY_HOST": "0.0.0.0",
        "RELAY_PORT": "5010",
        "RELAY_WORKERS": "1",
        "TOKENPLACE_RATE_LIMIT_STORAGE_URI": "memory://",
        "TOKENPLACE_RATE_LIMIT_TRUSTED_PROXIES": "",
        "API_RATE_LIMIT": "60/hour",
        "API_DAILY_QUOTA": "1000/day",
        "XDG_CONFIG_HOME": "/tmp/config",
        "XDG_DATA_HOME": "/tmp/data",
        "XDG_CACHE_HOME": "/tmp/cache",
        "XDG_STATE_HOME": "/tmp/state",
    }
    for kind in ("requests", "limits"):
        assert container["resources"][kind]["memory"] == "256Mi"
    assert pod["volumes"] == [{"name": "tmp", "emptyDir": {"sizeLimit": "32Mi"}}]
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"] == {"drop": ["ALL"]}
    assert container["readinessProbe"]["httpGet"]["path"] == "/healthz"
    assert container["livenessProbe"]["httpGet"]["path"] == "/livez"
    (account,) = by_kind(objects, "ServiceAccount")
    assert account["automountServiceAccountToken"] is False


def test_only_designated_same_namespace_runner_can_reach_relay(objects):
    policies = {p["metadata"]["name"]: p["spec"] for p in by_kind(objects, "NetworkPolicy")}
    assert len(policies) == 3
    assert policies["tokenplace-k243-default-deny"] == {
        "podSelector": {},
        "policyTypes": ["Ingress", "Egress"],
        "ingress": [],
        "egress": [],
    }
    relay = {
        "matchLabels": {
            "app.kubernetes.io/name": "tokenplace-k243-relay",
            "sugarkube.dev/k243-run": "offline-fixture",
        }
    }
    runner = {
        "matchLabels": {
            "app.kubernetes.io/name": "tokenplace-k243-runner",
            "sugarkube.dev/k243-run": "offline-fixture",
        }
    }
    ports = [{"protocol": "TCP", "port": 5010}]
    assert policies["tokenplace-k243-relay-ingress"] == {
        "podSelector": relay,
        "policyTypes": ["Ingress"],
        "ingress": [{"from": [{"podSelector": runner}], "ports": ports}],
    }
    assert policies["tokenplace-k243-runner-egress"] == {
        "podSelector": runner,
        "policyTypes": ["Egress"],
        "egress": [{"to": [{"podSelector": relay}], "ports": ports}],
    }


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("--set", "runId="),
        ("--set", "runId=UPPER"),
        ("--set", "runId=offline", "--set", "replicas=2"),
        ("--set", "runId=offline", "--set", "ingress.enabled=true"),
        ("--set", "runId=offline", "--set", "image.tag=latest"),
    ],
)
def test_unsafe_or_missing_values_fail_render(args):
    assert render(*args).returncode != 0


def test_serving_namespace_is_rejected():
    assert render("--set", "runId=offline", namespace="tokenplace").returncode != 0


def test_lane_is_not_reconciled_by_flux():
    for directory in ("clusters", "flux", "platform"):
        for path in (ROOT / directory).rglob("*.yaml"):
            assert "tokenplace-test-lane" not in path.read_text()
    schema = json.loads((CHART / "values.schema.json").read_text())
    assert schema["additionalProperties"] is False
