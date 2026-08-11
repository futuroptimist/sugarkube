import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("audit", ROOT / "scripts/prod_resilience_audit.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_endpoint_slices_use_effective_conditions_and_deduplicate():
    slices = [
        {
            "metadata": {"labels": {"kubernetes.io/service-name": "traefik"}},
            "endpoints": [
                {"addresses": ["10.0.0.2"], "nodeName": "sugarkube1", "targetRef": {"uid": "a"}},
                {
                    "addresses": ["10.0.0.3"],
                    "nodeName": "sugarkube2",
                    "targetRef": {"uid": "b"},
                    "conditions": {"ready": True, "serving": True},
                },
            ],
        },
        {
            "metadata": {"labels": {"kubernetes.io/service-name": "traefik"}},
            "endpoints": [
                {
                    "addresses": ["10.0.0.2"],
                    "nodeName": "sugarkube1",
                    "targetRef": {"uid": "a"},
                    "conditions": {"terminating": True},
                }
            ],
        },
    ]
    result = audit.epsummary(slices, "traefik")
    assert result == {
        "service": "traefik",
        "slices": 2,
        "uniqueEndpoints": 2,
        "healthyEndpoints": 1,
        "healthyNodes": ["sugarkube2"],
        "unhealthyEndpoints": 1,
    }


@pytest.mark.parametrize(
    "command",
    [
        ["kubectl", "apply", "-f", "x"],
        ["kubectl", "exec", "p"],
        ["helm", "upgrade", "release", "chart"],
        ["helm", "repo", "add", "x", "y"],
    ],
)
def test_command_boundary_rejects_mutation(command):
    with pytest.raises(audit.AuditError, match="mutating"):
        audit.run(command)


def test_helmchartconfig_snapshot_does_not_retain_arbitrary_values():
    resource = {
        "metadata": {"name": "traefik", "labels": {"owner": "audit"}},
        "spec": {"valuesContent": "private-field: connector-id-123"},
    }
    rendered = json.dumps(audit.owned_config(resource))
    assert "private-field" not in rendered
    assert "connector-id" not in rendered
    assert "desiredConfigurationPresent" in rendered


def test_arbitrary_labels_are_not_retained():
    resource = {
        "metadata": {
            "labels": {
                "app.kubernetes.io/managed-by": "Helm",
                "cloudflare.example/connector-id": "sensitive-connector-id",
            }
        }
    }
    assert audit.ownership_labels(resource) == {"app.kubernetes.io/managed-by": "Helm"}


def test_cloudflare_image_contract_is_digest_pinned():
    assert audit.IMAGE.startswith("cloudflare/cloudflared:2026.7.3@sha256:")
    assert len(audit.IMAGE.rsplit("sha256:", 1)[1]) == 64


def test_target_manifest_is_exact_and_contains_no_legacy_staging_hosts():
    targets = json.loads((ROOT / "config/prod-resilience-audit-targets.json").read_text())
    assert set(targets) == {"democratized.space", "token.place", "danielsmith.io"}
    assert "/config.json" in targets["democratized.space"]
    assert "/api/v1/meta" in targets["token.place"]
    assert "staging" not in json.dumps(targets)


def test_gap_order_is_stable():
    gaps = [
        {"code": "Z", "detail": "a"},
        {"code": "A", "detail": "z"},
        {"code": "A", "detail": "a"},
    ]
    gaps.sort(key=lambda x: (x["code"], x["detail"]))
    assert [(x["code"], x["detail"]) for x in gaps] == [("A", "a"), ("A", "z"), ("Z", "a")]


def test_source_contains_no_secret_or_log_collection_commands():
    source = (ROOT / "scripts/prod_resilience_audit.py").read_text()
    assert 'items("secrets' not in source
    assert '"logs"' not in source
    assert "helm get values" not in source
    assert "cloudflare_wan_dependency_loss_drill" not in source
