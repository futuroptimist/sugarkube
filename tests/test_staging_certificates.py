"""Offline guards for staging certificate recovery tooling."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/staging_certificates.py"
SPEC = importlib.util.spec_from_file_location("staging_certificates", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def completed(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout, "")


def test_redaction_covers_sensitive_message_fields():
    text = MODULE.safe(
        "authorization: Bearer-example api_" + "tok" + "en=supersecret secret: value"
    )
    assert "supersecret" not in text
    assert "Bearer-example" not in text
    assert "secret: value" not in text
    assert text.count("[REDACTED]") == 3


def test_mutation_guard_rejects_non_staging(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_ENV", "prod")
    with pytest.raises(SystemExit, match="staging-only"):
        MODULE.guard()


def test_mutation_guard_rejects_wrong_context(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_ENV", "staging")
    monkeypatch.setattr(MODULE, "run", lambda *args, **kwargs: completed("production\n"))
    with pytest.raises(SystemExit, match="exactly sugar-staging"):
        MODULE.guard()


def test_status_parses_failure_without_secret_data(monkeypatch, capsys):
    cert = {
        "metadata": {"namespace": "sample", "name": "web"},
        "spec": {
            "secretName": "web-tls",
            "dnsNames": ["staging.example.test"],
            "issuerRef": {"kind": "ClusterIssuer", "name": "letsencrypt-production"},
        },
        "status": {
            "revision": 1,
            "conditions": [{"type": "Ready", "status": "False", "reason": "DoesNotExist"}],
        },
    }
    challenge = {
        "metadata": {
            "namespace": "sample",
            "name": "challenge",
            "ownerReferences": [{"name": "order"}],
        },
        "status": {
            "state": "pending",
            "reason": "Found no Zones; api-" + "tok" + "en=do-not-print",
        },
    }
    request = {
        "metadata": {
            "namespace": "sample",
            "name": "request",
            "ownerReferences": [{"name": "web"}],
        },
        "status": {},
    }
    order = {
        "metadata": {
            "namespace": "sample",
            "name": "order",
            "ownerReferences": [{"name": "request"}],
        },
        "status": {"state": "pending"},
    }
    fixtures = {
        "certificates.cert-manager.io": [cert],
        "certificaterequests.cert-manager.io": [request],
        "orders.acme.cert-manager.io": [order],
        "challenges.acme.cert-manager.io": [challenge],
    }
    monkeypatch.setattr(MODULE, "load", lambda kind: fixtures.get(kind, []))
    monkeypatch.setattr(MODULE, "kubectl", lambda *args, **kwargs: completed(code=1))
    assert MODULE.status(["sample/web"]) == 1
    output = capsys.readouterr().out
    assert "CertificateRequests:" in output and "Orders:" in output and "Challenge:" in output
    assert "do-not-print" not in output and "[REDACTED]" in output


def test_token_command_structure_never_places_value_in_argv(monkeypatch, tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("unique-sensitive-value", encoding="utf-8")
    calls = []
    monkeypatch.setattr(MODULE, "guard", lambda: None)

    def fake_run(args, **kwargs):
        calls.append((args, kwargs.get("input_text")))
        return completed("kind: Secret\n" if "create" in args else "")

    monkeypatch.setattr(MODULE, "run", fake_run)
    MODULE.install_token(str(token_file))
    assert all("unique-sensitive-value" not in " ".join(args) for args, _ in calls)
    assert any(
        arg.startswith("--from-file=api-") and arg.endswith("=/dev/stdin") for arg in calls[0][0]
    )
    assert calls[1][0][-2:] == ["-f", "-"]


def test_docs_and_justfile_have_no_unsafe_dns_token_guidance():
    combined = (
        (ROOT / "justfile").read_text()
        + (ROOT / "docs/runbook.md").read_text()
        + (ROOT / "docs/staging-cert-manager-cloudflare.md").read_text()
    )
    assert "cert-manager-cloudflare-token-secret " + "tok" + "en=" not in combined
    assert "--from-literal=api-token" not in combined
    assert "CF_DNS_API_TOKEN" not in combined
