import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/staging_certificate_ops.py"
spec = importlib.util.spec_from_file_location("certificate_ops", SCRIPT)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


def resource(
    kind,
    name,
    namespace="app",
    uid=None,
    owner=None,
    status=None,
    spec=None,
    created="2026-01-01T00:00:00Z",
):
    metadata = {
        "name": name,
        "namespace": namespace,
        "uid": uid or name,
        "creationTimestamp": created,
    }
    if owner:
        metadata["ownerReferences"] = [{"kind": owner[0], "uid": owner[1]}]
    return {"kind": kind, "metadata": metadata, "status": status or {}, "spec": spec or {}}


def test_sanitize_is_bounded_and_removes_hostile_material():
    hostile = (
        "Authorization: Bearer abc token=supersecret https://acme.test/path?q=secret "
        "-----BEGIN PRIVATE KEY----- xyz"
    )
    value = ops.sanitize(hostile)
    assert len(value) <= 241
    for forbidden in ("abc", "supersecret", "acme.test", "PRIVATE KEY", "?q="):
        assert forbidden not in value


def test_owner_correlation_active_and_stale(monkeypatch):
    cert = resource(
        "Certificate",
        "app-tls",
        uid="cert",
        spec={
            "dnsNames": ["staging.example.test"],
            "secretName": "app-tls",
            "issuerRef": {"kind": "ClusterIssuer", "name": "issuer"},
        },
        status={"conditions": [{"type": "Ready", "status": "False", "reason": "DoesNotExist"}]},
    )
    old = resource(
        "CertificateRequest",
        "opaque-old",
        uid="old",
        owner=("Certificate", "cert"),
        created="2025-01-01T00:00:00Z",
    )
    new = resource(
        "CertificateRequest",
        "opaque-new",
        uid="new",
        owner=("Certificate", "cert"),
        created="2026-01-01T00:00:00Z",
    )
    order_old = resource("Order", "random-a", uid="oa", owner=("CertificateRequest", "old"))
    order_new = resource("Order", "random-b", uid="ob", owner=("CertificateRequest", "new"))
    stale = resource(
        "Challenge",
        "unrelated-name-1",
        owner=("Order", "oa"),
        status={"state": "invalid", "reason": "Found no Zones"},
    )
    active = resource(
        "Challenge",
        "unrelated-name-2",
        owner=("Order", "ob"),
        status={"state": "pending", "reason": "Found no Zones"},
    )
    responses = {
        "certificates": [cert],
        "certificaterequests": [old, new],
        "orders.acme.cert-manager.io": [order_old, order_new],
        "challenges.acme.cert-manager.io": [stale, active],
        "clusterissuers.cert-manager.io": [resource("ClusterIssuer", "issuer")],
    }
    monkeypatch.setattr(ops, "run_json", lambda context, args: {"items": responses[args[1]]})
    monkeypatch.setattr(
        ops.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a, 0, "api-token\n" if "go-template" in " ".join(a[0]) else "secret/app-tls\n", ""
        ),
    )
    inv = {
        "context": "sugar-staging",
        "issuerSecret": {
            "namespace": "cert-manager",
            "name": "cloudflare-api-token",
            "key": "api-token",
        },
        "certificates": [
            {"namespace": "app", "name": "app-tls", "dnsNames": ["staging.example.test"]}
        ],
    }
    output, healthy = ops.collect(inv)
    assert not healthy
    assert "unrelated-name-1 classification=stale" in output
    assert "unrelated-name-2 classification=active" in output
    assert output == ops.collect(inv)[0]


def test_inventory_has_all_shared_zones_and_multiple_apps():
    inventory = json.loads((ROOT / "clusters/staging/certificates.json").read_text())
    assert inventory["zones"] == ["danielsmith.io", "jobbot3000.tech", "token.place"]
    assert len(inventory["certificates"]) == 3


def test_staging_guards_and_secret_installer_contract():
    source = SCRIPT.read_text()
    shell = (ROOT / "scripts/install_staging_cloudflare_token.sh").read_text()
    just = (ROOT / "justfile").read_text()
    assert 'args.env != "staging"' in source
    assert "current-context" in source and "select exactly one" in source
    assert "time.monotonic()" in source and "min(args.timeout, 900)" in source
    assert source.index("collect(inventory)") < source.index('"cmctl",')
    assert "read -r -s token" in shell
    assert "--from-file=api-token=/dev/stdin" in shell
    assert "trap cleanup EXIT INT TERM" in shell and "set +x" in shell
    assert "delete certificate" not in (source + shell + just).lower()
    assert "--from-literal=api-token" not in just


def test_docs_keep_certificate_layers_separate_and_no_legacy_token_argument():
    docs = (ROOT / "docs/staging-certificate-operations.md").read_text()
    runbook = (ROOT / "docs/runbook.md").read_text()
    assert "token.place" in docs and "independent" in docs
    assert "Their issuers and serials need not match" in docs
    assert "token=<token>" not in runbook
    assert "tls.key" in docs and "Never select" in docs
