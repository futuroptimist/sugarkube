import json
import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).parents[1]
REPORT = ROOT / "scripts/staging_cert_manager.py"
SCRIPT = ROOT / "scripts/staging_cert_manager.sh"
JUSTFILE = (ROOT / "justfile").read_text()
DOC = (ROOT / "docs/staging-cert-manager-recovery.md").read_text()


def resource(name, namespace="demo", *, owner=None, state=None, message=None):
    item = {"metadata": {"name": name, "namespace": namespace}, "status": {}}
    if owner:
        item["metadata"]["ownerReferences"] = [{"name": owner}]
    if state:
        item["status"]["state"] = state
    if message:
        item["status"]["conditions"] = [
            {"type": "Ready", "status": "False", "reason": "Pending", "message": message}
        ]
    return item


def document():
    cert = resource("site-tls")
    cert["spec"] = {
        "secretName": "site-tls",
        "dnsNames": ["staging.example.test"],
        "issuerRef": {"kind": "ClusterIssuer", "name": "letsencrypt-production"},
    }
    cert["status"] = {
        "revision": 2,
        "notBefore": "2026-01-01Z",
        "notAfter": "2026-04-01Z",
        "renewalTime": "2026-03-01Z",
        "conditions": [
            {
                "type": "Ready",
                "status": "True",
                "reason": "Ready",
                "message": "Certificate is current",
            }
        ],
    }
    request = resource("site-tls-2", owner="site-tls")
    order = resource("site-tls-2-abc", owner="site-tls-2", state="valid")
    old = resource("old", owner="site-tls-2-abc", state="valid")
    challenge = resource(
        "challenge",
        owner="site-tls-2-abc",
        state="pending",
        message="credential bearer-material",
    )
    return {
        "inventory": ["demo/site-tls/staging.example.test"],
        "secrets": {"demo": {"site-tls": True}},
        "resources": {
            "certificates": {"items": [cert]},
            "requests": {"items": [request]},
            "orders": {"items": [order]},
            "challenges": {"items": [old, challenge]},
            "issuers": {
                "items": [
                    {
                        "metadata": {"name": "letsencrypt-production"},
                        "status": {
                            "conditions": [
                                {
                                    "type": "Ready",
                                    "status": "True",
                                    "reason": "ACMEAccountRegistered",
                                }
                            ]
                        },
                    }
                ]
            },
            "events": {
                "items": [
                    {
                        "metadata": {"namespace": "demo"},
                        "involvedObject": {"name": "challenge"},
                        "reason": "PresentError",
                        "message": "Found no Zones",
                    }
                ]
            },
        },
    }


def test_redacted_report_and_active_stale_parsing():
    raw = json.dumps(document())
    result = subprocess.run([REPORT], input=raw, text=True, capture_output=True)
    assert result.returncode == 0
    assert "Revision: 2" in result.stdout
    assert "Issuer Ready: True" in result.stdout
    assert "Certificate DNS names: staging.example.test" in result.stdout
    assert "Secret present: True" in result.stdout
    assert "challenge: active state=pending" in result.stdout
    assert "old: stale/complete state=valid" in result.stdout
    assert "bearer-material" not in result.stdout
    assert "[redacted]" in result.stdout
    assert "Found no Zones" in result.stdout


def test_missing_certificate_and_malformed_issuer_fail():
    missing = document()
    missing["inventory"] = ["demo/missing/staging.example.test"]
    assert subprocess.run([REPORT], input=json.dumps(missing), text=True).returncode == 1
    malformed = document()
    malformed["resources"]["certificates"]["items"][0]["spec"]["issuerRef"] = {}
    assert subprocess.run([REPORT], input=json.dumps(malformed), text=True).returncode == 1


def test_mutation_guard_runs_before_commands(tmp_path):
    kubectl = tmp_path / "kubectl"
    calls = tmp_path / "calls"
    kubectl.write_text(
        f'#!/bin/sh\necho "$*" >>"{calls}"\n'
        '[ "$*" = "config current-context" ] && echo production\n'
    )
    kubectl.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    result = subprocess.run(
        [SCRIPT, "install-token", "staging"],
        env=env,
        input="do-not-log-this\n",
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "exactly sugar-staging" in result.stderr
    assert calls.read_text().splitlines() == ["config current-context"]
    assert "do-not-log-this" not in result.stdout + result.stderr + calls.read_text()


def test_command_structure_has_no_unsafe_token_arguments():
    source = SCRIPT.read_text()
    assert "--from-file=api-token=/dev/stdin" in source
    assert "--from-literal=api-token" not in source
    recipe = JUSTFILE.split("cert-manager-cloudflare-token-secret:", 1)[1].split(
        "# Apply non-Flux", 1
    )[0]
    assert "--from-literal" not in recipe
    assert 'cmctl renew -n "$ns" "$cert"' in source
    assert '--timeout="$TIMEOUT"' in source
    assert '-verify_hostname "$host" -verify_return_error' in source


def test_docs_define_generic_inventory_permissions_and_boundaries():
    assert "SUGARKUBE_STAGING_CERTIFICATES" in DOC
    assert "Zone / Zone / Read" in DOC and "Zone / DNS / Edit" in DOC
    for zone in ("token.place", "danielsmith.io", "jobbot3000.tech"):
        assert zone in DOC
    assert "duplicate-certificate" in DOC
    assert "must not be changed" in DOC
