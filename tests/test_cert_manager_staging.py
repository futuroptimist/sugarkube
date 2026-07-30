from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "cert_manager_staging", ROOT / "scripts/cert_manager_staging.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def resource(kind: str, name: str, namespace: str = "demo", owner: str = "") -> dict:
    meta = {"name": name, "namespace": namespace}
    if owner:
        meta["ownerReferences"] = [{"name": owner}]
    return {
        "apiVersion": "cert-manager.io/v1",
        "kind": kind,
        "metadata": meta,
        "status": {},
    }


def test_render_status_relates_resources_and_redacts_messages() -> None:
    cert = resource("Certificate", "demo-tls")
    cert.update(
        {
            "spec": {
                "secretName": "demo-secret",
                "dnsNames": ["staging.example.test"],
                "issuerRef": {
                    "kind": "ClusterIssuer",
                    "name": "letsencrypt-production",
                },
            },
            "status": {
                "revision": 2,
                "notBefore": "2026-01-01",
                "notAfter": "2026-04-01",
                "renewalTime": "2026-03-01",
                "conditions": [{"type": "Ready", "status": "True", "reason": "Ready"}],
            },
        }
    )
    cert["_secretPresent"] = True
    issuer = resource("ClusterIssuer", "letsencrypt-production", namespace="")
    issuer["spec"] = {
        "acme": {
            "solvers": [
                {
                    "dns01": {
                        "cloudflare": {
                            "apiTokenSecretRef": {
                                "name": "cloudflare-api-token",
                                "key": "api-token",
                            }
                        }
                    }
                }
            ]
        }
    }
    req = resource("CertificateRequest", "demo-2", owner="demo-tls")
    order = resource("Order", "demo-2-order", owner="demo-2")
    challenge = resource("Challenge", "demo-2-challenge", owner="demo-2-order")
    challenge["status"] = {
        "state": "pending",
        "reason": "authorization: Bearer super-secret",
    }
    event = {
        "involvedObject": {
            "apiVersion": "acme.cert-manager.io/v1",
            "kind": "Challenge",
            "name": "demo-2-challenge",
            "namespace": "demo",
        },
        "reason": "PresentError",
        "message": "authorization: Bearer never-print-this",
    }
    output = MODULE.render_status(
        {
            "clusterissuers": [issuer],
            "certificates": [cert],
            "certificaterequests": [req],
            "orders": [order],
            "challenges": [challenge],
            "events": [event],
        },
        True,
    )
    for expected in (
        "Issuer: ClusterIssuer/letsencrypt-production",
        "CloudflareSecret=cloudflare-api-token/api-token",
        "demo/demo-tls",
        "Ready: True",
        "revision: 2",
        "notAfter=2026-04-01",
        "staging.example.test",
        "CertificateRequest: demo-2",
        "Order: demo-2-order",
        "Challenge: demo-2-challenge",
        "present=yes",
        "[REDACTED]",
    ):
        assert expected in output
    assert "super-secret" not in output
    assert "never-print-this" not in output


def test_render_status_handles_missing_issuer_and_stale_unrelated_challenge() -> None:
    cert = resource("Certificate", "current")
    cert["spec"] = {"secretName": "current-tls"}
    stale = resource("Challenge", "old", owner="old-order")
    output = MODULE.render_status(
        {
            "clusterissuers": [],
            "certificates": [cert],
            "certificaterequests": [],
            "orders": [],
            "challenges": [stale],
            "events": [],
        },
        False,
    )
    assert "issuer: Issuer/<missing>" in output
    assert "Challenge: none" in output
    assert "old-order" not in output
    assert "present=no" in output


def test_command_structure_never_accepts_token_argument_or_literal() -> None:
    script = (ROOT / "scripts/cert_manager_staging.py").read_text()
    justfile = (ROOT / "justfile").read_text()
    runbook = (ROOT / "docs/runbook.md").read_text()
    assert "--from-file={SECRET_KEY}=/dev/stdin" in script
    assert "--from-literal=api-token" not in script + justfile + runbook
    assert ("token" + "=<cloudflare") not in script + justfile + runbook
    assert "--insecure" not in script
    assert 'CONTEXT = "sugar-staging"' in script
    assert "30 <= args.timeout <= 600" in script


def test_active_challenge_parser_excludes_stale_and_completed_challenges() -> None:
    cert = resource("Certificate", "current")
    request = resource("CertificateRequest", "current-1", owner="current")
    order = resource("Order", "current-order", owner="current-1")
    pending = resource("Challenge", "pending", owner="current-order")
    pending["status"] = {"state": "pending", "reason": "Found no Zones"}
    valid = resource("Challenge", "valid", owner="current-order")
    valid["status"] = {"state": "valid", "reason": "Found no Zones (old message)"}
    stale = resource("Challenge", "stale", owner="unrelated-order")
    data = {
        "certificates": [cert],
        "certificaterequests": [request],
        "orders": [order],
        "challenges": [pending, valid, stale],
    }
    assert MODULE.active_challenges(data) == [pending]


def test_redaction_covers_failure_output() -> None:
    assert (
        MODULE.safe("authorization: Bearer forbidden-value")
        == "authorization=[REDACTED]"
    )
    assert MODULE.safe("ordinary controller failure") == "ordinary controller failure"


def test_docs_define_zone_contract_boundaries_and_rollback() -> None:
    docs = (ROOT / "docs/runbook.md").read_text()
    for value in (
        "Zone / Zone / Read",
        "Zone / DNS / Edit",
        "token.place",
        "danielsmith.io",
        "jobbot3000.tech",
        "duplicate-certificate",
        "Restore the prior known-good token",
        "separate hardening issue",
        "one Helm-managed",
    ):
        assert value in docs
