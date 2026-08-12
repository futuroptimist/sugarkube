"""Focused offline contracts for the production resilience collector."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "prod_audit", ROOT / "scripts/prod_resilience_audit.py"
)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def slices(endpoints_by_slice):
    return {
        "items": [
            {
                "metadata": {"labels": {"kubernetes.io/service-name": "traefik"}},
                "endpoints": endpoints,
            }
            for endpoints in endpoints_by_slice
        ]
    }


def test_endpoint_slices_aggregate_all_slices_and_effective_conditions() -> None:
    document = slices(
        [
            [{"addresses": ["10.0.0.1"], "nodeName": "a", "conditions": {}}],
            [
                {
                    "addresses": ["10.0.0.2"],
                    "nodeName": "b",
                    "conditions": {"ready": True, "serving": True, "terminating": False},
                },
                {
                    "addresses": ["10.0.0.3"],
                    "nodeName": "c",
                    "conditions": {"ready": True, "terminating": True},
                },
            ],
        ]
    )
    result = audit.endpoints(document, "traefik")
    assert result == {
        "service": "traefik",
        "slices": 2,
        "uniqueEndpoints": 3,
        "healthyEndpoints": 2,
        "unhealthyEndpoints": 1,
        "healthyNodes": ["a", "b"],
    }
    assert "10.0.0.1" not in json.dumps(result)


def test_conflicting_duplicate_endpoint_fails_closed() -> None:
    endpoint = {"addresses": ["10.0.0.1"], "nodeName": "a", "conditions": {"ready": True}}
    other = json.loads(json.dumps(endpoint))
    other["conditions"]["ready"] = False
    result = audit.endpoints(slices([[endpoint], [other]]), "traefik")
    assert result["healthyEndpoints"] == 0
    assert result["unhealthyEndpoints"] == 1


def test_deployment_snapshot_keeps_secret_reference_but_not_value() -> None:
    dep = {
        "metadata": {"name": "tunnel", "namespace": "cf", "uid": "pod-uid"},
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "cloudflared",
                            "image": "image@sha256:digest",
                            "env": [
                                {
                                    "name": "TUNNEL_TOKEN",
                                    "valueFrom": {
                                        "secretKeyRef": {"name": "tunnel-token", "key": "token"}
                                    },
                                }
                            ],
                        }
                    ]
                }
            }
        },
    }
    result = audit.deployment_snapshot(dep)
    encoded = json.dumps(result)
    assert "tunnel-token" in encoded
    assert '"value"' not in encoded
    assert "connector" not in encoded.lower()


@pytest.mark.parametrize(
    "argv",
    [
        ["kubectl", "apply", "-f", "x"],
        ["kubectl", "rollout", "restart", "deployment/x"],
        ["kubectl", "exec", "pod/x"],
        ["helm", "upgrade", "x", "chart"],
        ["helm", "repo", "add", "x", "url"],
    ],
)
def test_internal_runner_rejects_mutation_before_execution(monkeypatch, argv) -> None:
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(audit.subprocess, "run", forbidden)
    with pytest.raises(audit.HardFailure, match="safety policy"):
        audit.run(argv)
    assert called is False


def test_source_has_no_cluster_mutation_or_dormant_flux_discovery() -> None:
    source = (ROOT / "scripts/prod_resilience_audit.py").read_text()
    for forbidden in ("flux reconcile", "systemctl", "nftables", "poweroff"):
        assert forbidden not in source
    assert '["kubectl", "port-forward"' not in source
    assert "platform/cloudflared" not in source
    assert "cloudflared-values.yaml" not in source


def test_target_manifest_is_canonical_and_narrow() -> None:
    targets = json.loads((ROOT / "config/prod-resilience-audit-targets.json").read_text())
    assert sorted(targets) == ["danielsmith.io", "democratized.space", "token.place"]
    assert all(path.startswith("/") for paths in targets.values() for path in paths)


@pytest.mark.parametrize("value", [0, "0"])
def test_int_or_string_comparison_accepts_kubernetes_encodings(value) -> None:
    assert audit.int_or_string_equals(value, 0)


@pytest.mark.parametrize("value", [None, 1, "1", False])
def test_int_or_string_comparison_rejects_other_values(value) -> None:
    assert not audit.int_or_string_equals(value, 0)


def test_runner_failure_includes_bounded_diagnostics(monkeypatch) -> None:
    result = subprocess.CompletedProcess(
        ["kubectl", "get", "nodes"], 7, stderr="permission denied " + "x" * 600
    )
    monkeypatch.setattr(audit.subprocess, "run", lambda *args, **kwargs: result)

    with pytest.raises(audit.HardFailure) as caught:
        audit.run(["kubectl", "get", "nodes"])

    message = str(caught.value)
    assert "exit 7" in message
    assert "kubectl get nodes" in message
    assert "permission denied" in message
    assert len(message) < 600


def test_successful_status_with_transport_error_is_unhealthy() -> None:
    assert audit.probes_unhealthy([{"status": 200, "error": "transport"}])
    assert not audit.probes_unhealthy([{"status": 204}])


@pytest.mark.parametrize("targets", [{}, {"example.com": []}, []])
def test_empty_probe_targets_fail_closed(targets) -> None:
    with pytest.raises(audit.HardFailure, match="target manifest"):
        audit.probe_urls(targets)
