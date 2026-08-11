"""Focused offline checks for the production resilience audit's safety primitives."""

from __future__ import annotations

import json
import pathlib

import pytest

from scripts import production_resilience_audit as audit

ROOT = pathlib.Path(__file__).parents[1]


def test_endpoint_slices_aggregate_duplicates_and_effective_conditions() -> None:
    endpoint = {"addresses": ["10.0.0.1"], "nodeName": "sugarkube0"}
    doc = {
        "items": [
            {
                "metadata": {"labels": {"kubernetes.io/service-name": "traefik"}},
                "endpoints": [endpoint],
            },
            {
                "metadata": {"labels": {"kubernetes.io/service-name": "traefik"}},
                "endpoints": [endpoint | {"conditions": {"serving": False}}],
            },
            {
                "metadata": {"labels": {"kubernetes.io/service-name": "traefik"}},
                "endpoints": [
                    {
                        "addresses": ["10.0.0.2"],
                        "nodeName": "sugarkube1",
                        "conditions": {"ready": True, "serving": True, "terminating": False},
                    }
                ],
            },
        ]
    }
    result = audit.endpoint_snapshot(doc, "traefik")
    assert result == {
        "service": "traefik",
        "sliceCount": 3,
        "uniqueEndpoints": 2,
        "healthyEndpoints": 1,
        "unhealthyEndpoints": 1,
        "healthyNodes": ["sugarkube1"],
    }


def test_metadata_and_lifecycle_never_retain_sensitive_values() -> None:
    obj = {
        "metadata": {
            "name": "tunnel",
            "labels": {"safe": "Helm", "connector-id": "DO_NOT_RETAIN"},
            "annotations": {"token": "DO_NOT_RETAIN", "safe": "value"},
        },
        "spec": {"valuesContent": "replicas: 2", "safe": 2},
    }
    evidence = {
        "metadata": audit.metadata(obj),
        "spec": audit.lifecycle_spec("helmchartconfig/x", obj),
    }
    encoded = json.dumps(evidence)
    assert "DO_NOT_RETAIN" not in encoded
    assert evidence["metadata"]["labels"] == {"safe": "Helm"}
    assert evidence["spec"]["safe"] == 2
    assert len(evidence["spec"]["valuesContentSha256"]) == 64


@pytest.mark.parametrize(
    "command",
    [
        ["kubectl", "apply", "-f", "x"],
        ["kubectl", "exec", "pod", "--", "sh"],
        ["helm", "upgrade", "release", "chart"],
        ["helm", "repo", "update"],
    ],
)
def test_mutation_commands_are_rejected_before_execution(monkeypatch, command) -> None:
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(audit.subprocess, "run", forbidden)
    with pytest.raises(audit.CollectionError, match="mutation command"):
        audit.run(command)
    assert not called


def test_repository_recipe_does_not_call_install_or_drill_lifecycles() -> None:
    recipe = (
        (ROOT / "justfile").read_text().split("prod-resilience-audit", 1)[1].split("\n\n", 1)[0]
    )
    assert "production_resilience_audit.py" in recipe
    assert "cf-tunnel-install" not in recipe
    assert "wan-dependency-loss-drill" not in recipe


def test_gap_order_is_stable() -> None:
    gaps = []
    audit.gap(gaps, "Z_GAP", "second")
    audit.gap(gaps, "A_GAP", "first")
    gaps.sort(key=lambda item: (item["code"], item["detail"]))
    assert [item["code"] for item in gaps] == ["A_GAP", "Z_GAP"]
