import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "certops", ROOT / "scripts/staging_certificate_ops.py"
)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
ENTRY = {
    "namespace": "app",
    "name": "app-staging-tls",
    "dnsNames": ["staging.example.test"],
    "zone": "example.test",
}
ISSUER = {"namespace": "cert-manager", "name": "cloudflare-api-token", "key": "api-token"}


def resource(
    kind, name, uid, owner_kind=None, owner_uid=None, status=None, created="2026-01-01T00:00:00Z"
):
    m = {"name": name, "uid": uid, "creationTimestamp": created}
    if owner_kind:
        m["ownerReferences"] = [{"kind": owner_kind, "uid": owner_uid, "controller": True}]
    return {"kind": kind, "metadata": m, "status": status or {}}


def fixture(active=True, healthy=False, malformed=False, stale=False):
    cert = resource("Certificate", "app-staging-tls", "cert")
    cert["spec"] = {
        "dnsNames": ["staging.example.test"],
        "secretName": "app-staging-tls",
        "issuerRef": {"kind": "ClusterIssuer", "name": "letsencrypt-production"},
    }
    cert["status"] = (
        {"revision": 1}
        if healthy
        else {"conditions": [{"type": "Ready", "status": "False", "reason": "DoesNotExist"}]}
    )
    req = resource("CertificateRequest", "req", "req", "Certificate", "cert")
    order = resource("Order", "order", "order", "CertificateRequest", "req")
    reason = "Found no Zones https://evil.invalid/?token=SUPERSECRET Authorization: Bearer PRIVATE -----BEGIN PRIVATE KEY----- bad -----END PRIVATE KEY-----"
    ch = resource(
        "Challenge",
        "challenge",
        "ch",
        "Order",
        "order",
        {"state": "pending", "processing": active, "reason": reason},
    )
    issuer = {
        "metadata": {"name": "letsencrypt-production"},
        "spec": {
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
        },
    }
    data = {
        "certificates": [cert],
        "certificaterequests": [req],
        "orders": [order],
        "challenges": [ch],
        "clusterissuers": [issuer],
    }
    if malformed:
        data["certificates"] = []
    if stale:
        ch["status"]["processing"] = False
    return data


def test_active_failure_is_owned_redacted_and_deterministic(monkeypatch):
    monkeypatch.setattr(
        ops,
        "secret_keys",
        lambda ns, name: "cloudflare-api-token|api-token" if ns == "cert-manager" else "",
    )
    out = ops.render(ENTRY, fixture(), ISSUER)
    assert out == ops.render(ENTRY, fixture(), ISSUER)
    assert "Challenge challenge: ACTIVE" in out and "TLS Secret: MISSING" in out
    for leaked in ("SUPERSECRET", "PRIVATE", "evil.invalid", "BEGIN PRIVATE KEY"):
        assert leaked not in out
    assert len(next(x for x in out.splitlines() if "reason=" in x)) < 240


def test_stale_healthy_missing_and_malformed(monkeypatch):
    monkeypatch.setattr(ops, "secret_keys", lambda *_: "name|tls.crt tls.key api-token")
    assert "STALE" in ops.render(ENTRY, fixture(stale=True), ISSUER)
    assert "TLS Secret: present" in ops.render(ENTRY, fixture(healthy=True), ISSUER)
    assert "MALFORMED_OR_MISSING" in ops.render(ENTRY, fixture(malformed=True), ISSUER)


def test_missing_issuer_and_key(monkeypatch):
    data = fixture()
    data["certificates"][0]["spec"]["issuerRef"] = {"kind": "ClusterIssuer"}
    monkeypatch.setattr(ops, "secret_keys", lambda *_: "")
    out = ops.render(ENTRY, data, ISSUER)
    assert "MISSING issuer" in out and "MISSING name/key" in out


def test_inventory_multiple_apps_and_preserves_working_zone():
    inv = json.loads((ROOT / "scripts/staging_certificate_inventory.json").read_text())
    assert len(inv["certificates"]) == 3
    assert {x["zone"] for x in inv["certificates"]} == {
        "token.place",
        "danielsmith.io",
        "jobbot3000.tech",
    }


def test_installer_and_workflow_are_secret_safe_and_nondestructive():
    installer = (ROOT / "scripts/install_staging_cloudflare_token.sh").read_text()
    program = (ROOT / "scripts/staging_certificate_ops.py").read_text()
    assert "read -r -s token" in installer and "set +x" in installer
    assert "--from-file=api-token=/dev/stdin" in installer and "unset token" in installer
    assert "from-literal" not in installer and "mktemp" not in installer
    assert 'a.command == "renew"' in program and program.index(
        'a.command == "renew"'
    ) > program.index("deadline = time.monotonic")
    assert '"cmctl"' in program and '"renew"' in program
    for destructive in ("kubectl delete", "delete certificate", "delete order", "delete challenge"):
        assert destructive not in program.lower()
    assert "tls\\\\.key" not in program and ".data.tls\\\\.crt" in program


def test_rejects_wrong_environment_before_cluster_access(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "ops",
            "status",
            "--env",
            "prod",
            "--namespace",
            "app",
            "--certificate",
            "app-staging-tls",
        ],
    )
    try:
        ops.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("non-staging accepted")


def test_wrong_context_rejected(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "ops",
            "status",
            "--env",
            "staging",
            "--namespace",
            "app",
            "--certificate",
            "app-staging-tls",
        ],
    )
    monkeypatch.setattr(ops, "run", lambda *a, **k: "production\n")
    try:
        ops.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("wrong context accepted")
