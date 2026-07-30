import importlib.util
import json
from pathlib import Path

PATH = Path(__file__).parents[1] / "scripts/staging_certificates.py"
SPEC = importlib.util.spec_from_file_location("staging_certificates", PATH)
certs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(certs)


def resource(kind, name, namespace="app", owner_kind=None, owner_name=None, status=None):
    metadata = {"name": name, "namespace": namespace}
    if owner_kind:
        metadata["ownerReferences"] = [{"kind": owner_kind, "name": owner_name}]
    return {"kind": kind, "metadata": metadata, "status": status or {}}


def test_owner_correlation_active_stale_and_redaction():
    inventory = {
        "clusterIssuer": "issuer",
        "cloudflareSecret": {"namespace": "cm", "name": "cf", "key": "api-token"},
        "certificates": [
            {"namespace": "app", "name": "one", "dnsNames": ["one.example"], "zone": "example"},
            {"namespace": "other", "name": "two", "dnsNames": ["two.test"], "zone": "test"},
        ],
    }
    certificate = resource(
        "Certificate",
        "one",
        status={
            "revision": 1,
            "conditions": [{"type": "Ready", "status": "False", "reason": "DoesNotExist"}],
        },
    )
    certificate["spec"] = {
        "dnsNames": ["one.example"],
        "secretName": "one",
        "issuerRef": {"kind": "ClusterIssuer", "name": "issuer"},
    }
    request = resource(
        "CertificateRequest", "random-request", owner_kind="Certificate", owner_name="one"
    )
    order = resource(
        "Order",
        "random-order",
        owner_kind="CertificateRequest",
        owner_name="random-request",
        status={"state": "pending"},
    )
    active = resource(
        "Challenge",
        "random-active",
        owner_kind="Order",
        owner_name="random-order",
        status={
            "state": "pending",
            "reason": "Found no Zones https://host/path?q=SECRET Authorization: Bearer_SECRET",
        },
    )
    stale_order = resource(
        "Order",
        "old-order",
        owner_kind="CertificateRequest",
        owner_name="random-request",
        status={"state": "invalid"},
    )
    stale = resource(
        "Challenge",
        "old",
        owner_kind="Order",
        owner_name="old-order",
        status={"state": "pending", "reason": "-----BEGIN PRIVATE KEY----- bad"},
    )
    data = {
        "certificates": [certificate],
        "certificaterequests": [request],
        "orders": [order, stale_order],
        "challenges": [active, stale],
    }
    issuer = {
        "metadata": {"name": "issuer"},
        "spec": {
            "acme": {
                "solvers": [
                    {
                        "dns01": {
                            "cloudflare": {"apiTokenSecretRef": {"name": "cf", "key": "api-token"}}
                        }
                    }
                ]
            }
        },
    }
    output = certs.render(
        inventory,
        data,
        [{"metadata": {"namespace": "cm", "name": "cf"}, "data": {"api-token": None}}],
        issuer,
    )
    assert "random-active state=pending classification=active" in output
    assert "old state=pending classification=stale" in output
    assert "Bearer_SECRET" not in output and "PRIVATE KEY" not in output and "?q=" not in output
    assert "certificate=other/two" in output and "ready=Missing" in output
    assert output == certs.render(
        inventory,
        data,
        [{"metadata": {"namespace": "cm", "name": "cf"}, "data": {"api-token": None}}],
        issuer,
    )


def test_inventory_and_scripts_are_secret_safe_and_nondestructive():
    inventory = json.loads(
        (Path(__file__).parents[1] / "clusters/staging/certificates.json").read_text()
    )
    assert {x["zone"] for x in inventory["certificates"]} == {
        "token.place",
        "danielsmith.io",
        "jobbot3000.tech",
    }
    installer = (
        Path(__file__).parents[1] / "scripts/install_staging_cloudflare_token.sh"
    ).read_text()
    assert "read -r -s token" in installer
    assert "--from-file=api-token=/dev/stdin" in installer
    assert "from-literal" not in installer and "mktemp" not in installer
    implementation = PATH.read_text()
    assert "delete" not in implementation and "tls.key" not in implementation
    justfile = (Path(__file__).parents[1] / "justfile").read_text()
    renew = justfile[
        justfile.index("cert-renew certificate") : justfile.index(
            "# Decode only", justfile.index("cert-renew certificate")
        )
    ]
    assert renew.index("staging_certificates.py wait") < renew.index("cmctl renew")
    assert "timeout" in renew and "delete" not in renew
