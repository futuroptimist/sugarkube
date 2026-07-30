import importlib.util
import json
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "staging_cert_manager.py"
SPEC = importlib.util.spec_from_file_location("staging_cert_manager", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def resource(name, *, owner_kind=None, owner_name=None, status=None, spec=None, conditions=None):
    metadata = {"name": name}
    if owner_kind:
        metadata["ownerReferences"] = [{"kind": owner_kind, "name": owner_name}]
    value = {"metadata": metadata, "status": status or {}, "spec": spec or {}}
    if conditions:
        value["status"]["conditions"] = conditions
    return value


def test_inventory_renders_chain_redacts_and_marks_active_challenges(monkeypatch):
    certificate = resource(
        "site-tls",
        spec={
            "dnsNames": ["staging.example.test"],
            "secretName": "site-tls",
            "issuerRef": {"name": "letsencrypt-production", "kind": "ClusterIssuer"},
        },
        status={
            "revision": 2,
            "notBefore": "2026-07-01T00:00:00Z",
            "notAfter": "2026-10-01T00:00:00Z",
            "renewalTime": "2026-09-01T00:00:00Z",
        },
        conditions=[{"type": "Ready", "status": "True", "reason": "Ready"}],
    )
    request = resource("site-tls-2", owner_kind="Certificate", owner_name="site-tls")
    order = resource("site-tls-2-order", owner_kind="CertificateRequest", owner_name="site-tls-2")
    active = resource(
        "active",
        owner_kind="Order",
        owner_name="site-tls-2-order",
        spec={"dnsName": "staging.example.test"},
        status={"state": "pending", "reason": "authorization Bearer should-not-appear"},
    )
    stale = resource(
        "stale",
        owner_kind="Order",
        owner_name="site-tls-2-order",
        status={"state": "valid"},
    )
    responses = {
        "certificate": certificate,
        "clusterissuer": resource(
            "letsencrypt-production",
            spec={
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
            conditions=[{"type": "Ready", "status": "True", "reason": "ACMEAccountRegistered"}],
        ),
        "certificaterequests": {"items": [request]},
        "orders": {"items": [order]},
        "challenges": {"items": [active, stale]},
        "events": {
            "items": [
                {
                    "type": "Warning",
                    "reason": "PresentError",
                    "message": "Bearer should-not-appear",
                }
            ]
        },
    }

    def fake_json(args):
        return responses[next(item for item in responses if item in args)]

    monkeypatch.setattr(MODULE, "kubectl_json", fake_json)
    monkeypatch.setattr(
        MODULE,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, b"secret/site-tls\n", b""),
    )
    report = MODULE.inventory("example", "site-tls")
    rendered = json.dumps(report)
    assert report["certificate"]["secret"] == {"name": "site-tls", "present": True}
    assert report["issuer"]["expectedTokenSecretRefConfigured"] is True
    assert report["challenges"][0]["active"] is True
    assert report["challenges"][1]["active"] is False
    assert "should-not-appear" not in rendered
    assert "<redacted>" in rendered


def test_inventory_rejects_missing_issuer_reference(monkeypatch):
    monkeypatch.setattr(MODULE, "kubectl_json", lambda _args: resource("broken"))
    with pytest.raises(MODULE.OperationError, match="issuerRef.name"):
        MODULE.inventory("example", "broken")


@pytest.mark.parametrize("environment,context", [("prod", "sugar-staging"), ("staging", "prod")])
def test_staging_guard_rejects_wrong_environment_or_context(monkeypatch, environment, context):
    monkeypatch.setenv("SUGARKUBE_ENV", environment)
    monkeypatch.setattr(
        MODULE,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, context.encode(), b""),
    )
    with pytest.raises(MODULE.OperationError, match="refusing"):
        MODULE.staging_guard()


def test_command_and_docs_never_accept_visible_token_values():
    justfile = (ROOT / "justfile").read_text()
    docs = (ROOT / "docs" / "staging-cert-manager.md").read_text()
    implementation = SCRIPT.read_text()
    cert_recipe = justfile.split("cert-manager-cloudflare-token-secret", 1)[1].split(
        "cert-manager-certificate-status", 1
    )[0]
    assert "token" + "=<" not in cert_recipe + docs
    assert "--from-literal=api-token" not in justfile + implementation
    assert "--from-file=api-token=/dev/stdin" in implementation
    assert "token" + '="{{ token }}"' not in justfile
    assert "curl" in implementation
    assert "--insecure" not in implementation


def test_recover_reports_bounded_failure_without_curl(monkeypatch):
    states = [
        {
            "certificate": {
                "revision": 1,
                "notAfter": "old",
                "ready": "True",
                "secret": {"present": True},
            }
        }
    ]
    monkeypatch.setattr(MODULE, "staging_guard", lambda: None)
    monkeypatch.setattr(MODULE, "inventory", lambda *_args: states[0])
    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(MODULE, "run", fake_run)
    monkeypatch.setattr(MODULE.time, "sleep", lambda _seconds: None)
    ticks = iter([0, 2])
    monkeypatch.setattr(MODULE.time, "monotonic", lambda: next(ticks))
    with pytest.raises(MODULE.OperationError, match="bounded wait expired"):
        MODULE.recover("example", "site-tls", "staging.example.test", 1)
    assert commands == [["cmctl", "renew", "-n", "example", "site-tls"]]
