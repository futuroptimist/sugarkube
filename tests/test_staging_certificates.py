import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/staging_certificates.py"
spec = importlib.util.spec_from_file_location("staging_certificates", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def resource(
    kind,
    name,
    namespace="app",
    owner_kind=None,
    owner_name=None,
    created="2026-01-01T00:00:00Z",
    status=None,
    spec=None,
):
    metadata = {"name": name, "namespace": namespace, "creationTimestamp": created}
    if owner_kind:
        metadata["ownerReferences"] = [{"kind": owner_kind, "name": owner_name}]
    return {
        "apiVersion": "v1",
        "kind": kind,
        "metadata": metadata,
        "status": status or {},
        "spec": spec or {},
    }


def inventory():
    return {
        "issuerSecret": {
            "namespace": "cert-manager",
            "name": "cloudflare-api-token",
            "key": "api-token",
        },
        "certificates": [
            {"namespace": "app", "name": "a-tls", "dnsNames": ["a.example"], "zone": "example"},
            {"namespace": "other", "name": "b-tls", "dnsNames": ["b.example"], "zone": "example"},
        ],
    }


def bundle(active_reason="Found no Zones"):
    cert = resource(
        "Certificate",
        "a-tls",
        status={
            "conditions": [{"type": "Ready", "status": "False", "reason": "DoesNotExist"}],
            "_secretPresent": False,
        },
        spec={
            "dnsNames": ["a.example"],
            "secretName": "a-tls",
            "issuerRef": {"kind": "ClusterIssuer", "name": "letsencrypt-production"},
        },
    )
    old = resource("CertificateRequest", "old", owner_kind="Certificate", owner_name="a-tls")
    new = resource(
        "CertificateRequest",
        "new",
        owner_kind="Certificate",
        owner_name="a-tls",
        created="2026-02-01T00:00:00Z",
    )
    old_order = resource("Order", "old-order", owner_kind="CertificateRequest", owner_name="old")
    new_order = resource("Order", "new-order", owner_kind="CertificateRequest", owner_name="new")
    stale = resource(
        "Challenge",
        "stale",
        owner_kind="Order",
        owner_name="old-order",
        status={"state": "pending", "reason": "old failure"},
    )
    active = resource(
        "Challenge",
        "active",
        owner_kind="Order",
        owner_name="new-order",
        status={"state": "pending", "reason": active_reason},
    )
    return {
        module.KINDS[0]: [cert],
        module.KINDS[1]: [old, new],
        module.KINDS[2]: [old_order, new_order],
        module.KINDS[3]: [stale, active],
        "_issuerSecretValid": True,
    }


def test_owner_correlation_classifies_active_and_stale_and_missing_secret():
    output = module.render(bundle(), inventory())
    assert "Challenge active state=pending reason=Found no Zones" in output
    assert "Challenge stale state=pending reason=old failure" in output
    assert "expected Secret: a-tls (MISSING)" in output
    assert "Issuer Secret cert-manager/cloudflare-api-token key=api-token: valid" in output


def test_healthy_malformed_and_missing_issuer_are_deterministic():
    data = bundle()
    data[module.KINDS[0]][0]["status"] = {
        "conditions": [{"type": "Ready", "status": "True"}],
        "revision": 1,
        "notBefore": "now",
        "notAfter": "later",
        "renewalTime": "soon",
        "_secretPresent": True,
    }
    data["_issuerSecretValid"] = False
    assert module.render(data, inventory()) == module.render(data, inventory())
    output = module.render(data, inventory())
    assert output.index("Certificate app/a-tls") < output.index("Certificate other/b-tls")
    assert "Ready: True" in output and "revision: 1" in output
    assert "MISSING, WRONG KEY, OR ISSUER REFERENCE MISMATCH" in output
    assert "Certificate other/b-tls\n  DNS names: b.example\n  Ready: - reason=-" in output


def test_malicious_reasons_are_bounded_and_redacted():
    malicious = (
        "Authorization: Bearer supersecret https://evil.test/path?token=secret "
        + "x" * 500
        + " -----BEGIN PRIVATE KEY----- hidden"
    )
    output = module.render(bundle(malicious), inventory())
    for forbidden in ("supersecret", "evil.test", "?token=", "PRIVATE KEY", "hidden"):
        assert forbidden not in output
    reason = next(line for line in output.splitlines() if "Challenge active" in line)
    assert len(reason) < 300


def test_inventory_preserves_all_app_owned_zones():
    actual = json.loads((ROOT / "clusters/staging/certificates.json").read_text())
    assert {x["zone"] for x in actual["certificates"]} == {
        "token.place",
        "danielsmith.io",
        "jobbot3000.tech",
    }
    assert len({(x["namespace"], x["name"]) for x in actual["certificates"]}) == 3


def test_secret_and_controlled_operation_guards_are_static():
    installer = (ROOT / "scripts/install_staging_cloudflare_token.sh").read_text()
    ops = (ROOT / "scripts/staging_certificate_ops.sh").read_text()
    docs = (ROOT / "docs/staging-certificate-operations.md").read_text()
    assert "read -r -s" in installer
    assert "--from-file=api-token=/dev/stdin" in installer
    assert "--from-literal" not in installer
    assert "set +x" in installer and "unset token" in installer
    assert "sugar-staging" in installer and "sugar-staging" in ops
    assert "timeout >= 1 && timeout <= 900" in ops
    assert ops.index("observe && exit 0") < ops.index("cmctl renew")
    assert ops.count("observe") >= 3
    assert "cmctl renew" in ops and "delete certificate" not in ops.lower()
    assert '"tls.crt"' in ops and '"tls.key"' not in ops
    assert "separate layers" in docs and "token.place" in docs
