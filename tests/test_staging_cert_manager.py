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
        status={"state": "pending", "reason": "authorization Bearer challenge-token-value"},
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
                    "involvedObject": {"kind": "Challenge", "name": "active"},
                    "type": "Warning",
                    "reason": "PresentError",
                    "message": "Bearer event-token-value",
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
    assert "challenge-token-value" not in rendered
    assert "event-token-value" not in rendered
    assert "Bearer event-token-value" not in rendered
    assert "<redacted>" in rendered


def test_inventory_rejects_missing_issuer_reference(monkeypatch):
    monkeypatch.setattr(MODULE, "kubectl_json", lambda _args: resource("broken"))
    with pytest.raises(MODULE.OperationError, match="issuerRef.name"):
        MODULE.inventory("example", "broken")


@pytest.mark.parametrize(
    "stdout,expected",
    [(b"secret/site-tls\n", True), (b"", False)],
)
def test_secret_present_distinguishes_present_and_missing(monkeypatch, stdout, expected):
    commands = []
    monkeypatch.setattr(
        MODULE,
        "run",
        lambda command, **_kwargs: commands.append(command)
        or subprocess.CompletedProcess(command, 0, stdout, b""),
    )

    assert MODULE.secret_present("example", "site-tls") is expected
    assert commands == [
        [
            "kubectl",
            "--context",
            "sugar-staging",
            "-n",
            "example",
            "get",
            "secret",
            "site-tls",
            "--ignore-not-found=true",
            "-o",
            "name",
        ]
    ]


def test_inventory_propagates_redacted_secret_lookup_failure(monkeypatch):
    certificate = resource(
        "site-tls",
        spec={
            "secretName": "site-tls",
            "issuerRef": {"name": "issuer", "kind": "ClusterIssuer"},
        },
    )
    responses = {
        "certificate": certificate,
        "clusterissuer": resource("issuer"),
        "certificaterequests": {"items": []},
        "orders": {"items": []},
        "challenges": {"items": []},
    }
    monkeypatch.setattr(
        MODULE,
        "kubectl_json",
        lambda args: responses[next(item for item in responses if item in args)],
    )
    monkeypatch.setattr(
        MODULE,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 1, b"", b"Forbidden: Bearer sensitive-rbac-token"
        ),
    )

    with pytest.raises(
        MODULE.OperationError, match="kubectl failed while checking Secret"
    ) as caught:
        MODULE.inventory("example", "site-tls")

    assert "sensitive-rbac-token" not in str(caught.value)
    assert "<redacted>" in str(caught.value)


@pytest.mark.parametrize(
    "environment,context",
    [("prod", "sugar-staging"), ("unknown", "sugar-staging"), ("staging", "prod")],
)
def test_staging_guard_rejects_wrong_environment_or_context(monkeypatch, environment, context):
    monkeypatch.setenv("SUGARKUBE_ENV", environment)
    monkeypatch.setattr(
        MODULE,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, context.encode(), b""),
    )
    with pytest.raises(MODULE.OperationError, match="refusing"):
        MODULE.staging_guard()


def test_staging_guard_accepts_only_exact_context(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_ENV", "staging")
    monkeypatch.setattr(
        MODULE,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, b"sugar-staging\n", b""),
    )
    MODULE.staging_guard()
    monkeypatch.setattr(
        MODULE,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, b"sugar-staging-admin\n", b""),
    )
    with pytest.raises(MODULE.OperationError, match="expected"):
        MODULE.staging_guard()


def authorization_report(*, issuer_ready="True", expected_ref=True, challenges=None):
    return {
        "issuer": {"ready": issuer_ready, "expectedTokenSecretRefConfigured": expected_ref},
        "certificate": {"dnsNames": ["staging.example.test"]},
        "challenges": challenges or [],
    }


def test_verify_authorization_success_does_not_require_certificate_ready(monkeypatch, capsys):
    report = authorization_report()
    report["certificate"]["ready"] = "False"
    commands = []
    monkeypatch.setattr(MODULE, "staging_guard", lambda: None)
    monkeypatch.setattr(MODULE, "inventory", lambda *_args: report)
    monkeypatch.setattr(
        MODULE,
        "run",
        lambda command, **_kwargs: commands.append(command)
        or subprocess.CompletedProcess(command, 0, b"secret/cloudflare-api-token", b""),
    )
    assert MODULE.verify_authorization("example", "site-tls") is report
    assert commands == [
        [
            "kubectl",
            "--context",
            "sugar-staging",
            "-n",
            "cert-manager",
            "get",
            "secret",
            "cloudflare-api-token",
            "-o",
            "name",
        ]
    ]
    assert "dashboard scope" in capsys.readouterr().out


@pytest.mark.parametrize(
    "report,secret_code,message",
    [
        (authorization_report(), 1, "missing or inaccessible"),
        (authorization_report(expected_ref=False), 0, "Cloudflare solver"),
        (authorization_report(issuer_ready="False"), 0, "Ready=True"),
        (
            authorization_report(
                challenges=[{"active": True, "reason": "PresentError", "message": "Found no Zones"}]
            ),
            0,
            "zone authorization",
        ),
        (
            authorization_report(
                challenges=[{"active": True, "reason": "PresentError", "message": "Error: 9109"}]
            ),
            0,
            "invalid Cloudflare credentials",
        ),
        (
            authorization_report(
                challenges=[{"active": True, "reason": "PresentError", "message": "Error: 10502"}]
            ),
            0,
            "authentication throttling",
        ),
    ],
)
def test_verify_authorization_fails_closed(monkeypatch, report, secret_code, message):
    monkeypatch.setattr(MODULE, "staging_guard", lambda: None)
    monkeypatch.setattr(MODULE, "inventory", lambda *_args: report)
    monkeypatch.setattr(
        MODULE,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, secret_code, b"", b""),
    )
    with pytest.raises(MODULE.OperationError, match=message):
        MODULE.verify_authorization("example", "site-tls")


@pytest.mark.parametrize("state", ["valid", "expired", "invalid"])
def test_verify_authorization_ignores_terminal_challenge_errors(monkeypatch, state):
    report = authorization_report(
        challenges=[
            {
                "active": False,
                "state": state,
                "reason": "PresentError",
                "message": "Error: 9109: Invalid access token",
            }
        ]
    )
    monkeypatch.setattr(MODULE, "staging_guard", lambda: None)
    monkeypatch.setattr(MODULE, "inventory", lambda *_args: report)
    monkeypatch.setattr(
        MODULE,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, b"secret/name", b""),
    )

    assert MODULE.verify_authorization("example", "site-tls") is report


def test_verify_authorization_ignores_historical_error_events(monkeypatch):
    report = authorization_report(
        challenges=[{"active": True, "reason": "Pending", "message": "Waiting for DNS"}]
    )
    report["events"] = [
        {"reason": "PresentError", "message": "Error: 10502: Too many authentication failures"}
    ]
    monkeypatch.setattr(MODULE, "staging_guard", lambda: None)
    monkeypatch.setattr(MODULE, "inventory", lambda *_args: report)
    monkeypatch.setattr(
        MODULE,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, b"secret/name", b""),
    )

    assert MODULE.verify_authorization("example", "site-tls") is report


def test_kubectl_json_failure_is_redacted(monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 2, b"", b"pass" + b"word=visible-value"
        ),
    )
    with pytest.raises(MODULE.OperationError) as caught:
        MODULE.kubectl_json(["get", "certificate", "broken"])
    assert "visible-value" not in str(caught.value)


@pytest.mark.parametrize("credential", [b"x" * 32, b"v1.0-" + b"x" * 48])
def test_runtime_token_command_uses_valid_shapes_via_stdin(monkeypatch, capsys, credential):
    class Input:
        def isatty(self):
            return False

        buffer = type("Buffer", (), {"read": staticmethod(lambda: credential)})()

    commands = []

    class Process:
        def __init__(self, command, **_kwargs):
            commands.append(command)
            self.stdin = type(
                "Writer", (), {"write": lambda self, value: None, "close": lambda self: None}
            )()
            self.stdout = type("Reader", (), {"close": lambda self: None})()
            self.stderr = type("Errors", (), {"read": lambda self: b""})()
            self.returncode = 0

        def communicate(self):
            return b"", b""

        def wait(self):
            return 0

    monkeypatch.setattr(MODULE, "staging_guard", lambda: None)
    monkeypatch.setattr(MODULE.sys, "stdin", Input())
    monkeypatch.setattr(MODULE.subprocess, "Popen", Process)
    MODULE.install_token()
    rendered = " ".join(word for command in commands for word in command)
    output = rendered + capsys.readouterr().out
    assert credential.decode() not in output
    assert "--from-file=" + MODULE.TOKEN_SECRET_KEY + "=/dev/stdin" in rendered
    assert commands[0][1:3] == ["--context", "sugar-staging"]


def test_command_and_docs_never_accept_visible_token_values():
    justfile = (ROOT / "justfile").read_text()
    docs = (ROOT / "docs" / "staging-cert-manager.md").read_text()
    implementation = SCRIPT.read_text()
    cert_recipe = justfile.split("cert-manager-cloudflare-token-secret", 1)[1].split(
        "cert-manager-certificate-status", 1
    )[0]
    assert "token" + "=<" not in cert_recipe + docs
    assert "--from-literal=api-token" not in justfile + implementation
    assert 'f"--from-file={TOKEN_SECRET_KEY}=/dev/stdin"' in implementation
    assert "token" + '="{{ token }}"' not in justfile
    assert "curl" in implementation
    assert "--insecure" not in implementation


def test_recover_reports_bounded_failure_without_curl(monkeypatch):
    states = [
        {
            "certificate": {
                "dnsNames": ["staging.example.test"],
                "revision": 1,
                "notAfter": "old",
                "ready": "True",
                "secret": {"present": True},
            }
        }
    ]
    monkeypatch.setattr(MODULE, "verify_authorization", lambda *_args: states[0])
    monkeypatch.setattr(MODULE.shutil, "which", lambda _name: "/usr/bin/cmctl")
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
    assert commands == [
        ["cmctl", "--context", "sugar-staging", "renew", "-n", "example", "site-tls"]
    ]


def test_recover_rejects_host_not_named_by_certificate(monkeypatch):
    monkeypatch.setattr(MODULE.shutil, "which", lambda _name: "/usr/bin/cmctl")
    monkeypatch.setattr(
        MODULE,
        "verify_authorization",
        lambda *_args: {
            "certificate": {
                "dnsNames": ["staging.example.test"],
                "revision": 1,
                "notAfter": "old",
                "ready": "True",
                "secret": {"present": True},
            }
        },
    )
    commands = []
    monkeypatch.setattr(MODULE, "run", lambda command, **_kwargs: commands.append(command))

    with pytest.raises(MODULE.OperationError, match="not listed in Certificate DNS names"):
        MODULE.recover("example", "site-tls", "other.example.test", 60)

    assert commands == []


def test_recover_does_not_renew_when_active_authentication_is_blocked(monkeypatch):
    report = authorization_report(
        challenges=[{"active": True, "reason": "PresentError", "message": "Invalid access token"}]
    )
    monkeypatch.setattr(MODULE.shutil, "which", lambda _name: "/usr/bin/cmctl")
    monkeypatch.setattr(MODULE, "staging_guard", lambda: None)
    monkeypatch.setattr(MODULE, "inventory", lambda *_args: report)
    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, b"secret/name", b"")

    monkeypatch.setattr(MODULE, "run", fake_run)
    with pytest.raises(MODULE.OperationError, match="invalid Cloudflare credentials"):
        MODULE.recover("example", "site-tls", "staging.example.test", 60)

    assert not any(command[0] == "cmctl" for command in commands)


def test_kubectl_json_rejects_invalid_json(monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, b"not-json", b""),
    )

    with pytest.raises(MODULE.OperationError, match="invalid JSON"):
        MODULE.kubectl_json(["get", "certificate", "broken"])


def test_install_token_rejects_empty_input_before_starting_process(monkeypatch):
    class Input:
        def isatty(self):
            return False

        buffer = type("Buffer", (), {"read": staticmethod(lambda: b"  ")})()

    monkeypatch.setattr(MODULE, "staging_guard", lambda: None)
    monkeypatch.setattr(MODULE.sys, "stdin", Input())
    monkeypatch.setattr(
        MODULE.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("invalid input must not start kubectl"),
    )

    with pytest.raises(MODULE.OperationError, match="empty or malformed"):
        MODULE.install_token()


@pytest.mark.parametrize(
    "value",
    [
        b"Bearer " + b"x" * 24,
        b"legacy\tvalue",
        b"'" + b"x" * 24 + b"'",
        b'"' + b"x" * 24 + b'"',
    ],
)
def test_install_token_rejects_wrapped_or_whitespace_input_before_kubectl(monkeypatch, value):
    class Input:
        def isatty(self):
            return False

        buffer = type("Buffer", (), {"read": staticmethod(lambda: value)})()

    monkeypatch.setattr(MODULE, "staging_guard", lambda: None)
    monkeypatch.setattr(MODULE.sys, "stdin", Input())
    monkeypatch.setattr(
        MODULE.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("malformed input must not start kubectl"),
    )

    with pytest.raises(MODULE.OperationError, match="empty or malformed") as caught:
        MODULE.install_token()
    assert value.decode() not in str(caught.value)


def test_install_token_redacts_process_failure(monkeypatch):
    class Input:
        def isatty(self):
            return False

        buffer = type("Buffer", (), {"read": staticmethod(lambda: b"runtime-credential")})()

    class Process:
        instances = 0

        def __init__(self, _command, **_kwargs):
            self.number = Process.instances
            Process.instances += 1
            self.stdin = type(
                "Writer", (), {"write": lambda self, value: None, "close": lambda self: None}
            )()
            self.stdout = type("Reader", (), {"close": lambda self: None})()
            self.stderr = type(
                "Errors",
                (),
                {"read": lambda self: b"api-" + b"tok" + b"en=redaction-marker"},
            )()
            self.returncode = 1 if self.number else 0

        def communicate(self):
            return b"", b"pass" + b"word=apply-marker"

        def wait(self):
            return 0

    monkeypatch.setattr(MODULE, "staging_guard", lambda: None)
    monkeypatch.setattr(MODULE.sys, "stdin", Input())
    monkeypatch.setattr(MODULE.subprocess, "Popen", Process)

    with pytest.raises(MODULE.OperationError, match="credential output suppressed") as caught:
        MODULE.install_token()
    assert "apply-marker" not in str(caught.value)


def test_recover_success_checks_each_https_path(monkeypatch, capsys):
    monkeypatch.setattr(MODULE.shutil, "which", lambda _name: "/usr/bin/cmctl")
    before = {
        "certificate": {
            "dnsNames": ["staging.example.test"],
            "revision": 1,
            "notAfter": "old",
            "ready": "True",
            "secret": {"present": True},
        }
    }
    after = {
        "certificate": {
            **before["certificate"],
            "revision": 2,
            "notAfter": "new",
        }
    }
    commands = []
    monkeypatch.setattr(MODULE, "verify_authorization", lambda *_args: before)
    monkeypatch.setattr(MODULE, "inventory", lambda *_args: after)
    monkeypatch.setattr(
        MODULE,
        "run",
        lambda command, **_kwargs: commands.append(command)
        or subprocess.CompletedProcess(command, 0, b"", b""),
    )
    monkeypatch.setattr(MODULE.time, "monotonic", lambda: 0)

    MODULE.recover("example", "site-tls", "STAGING.EXAMPLE.TEST.", 60)

    curl_urls = [command[-1] for command in commands if command[0] == "curl"]
    assert curl_urls == [
        "https://STAGING.EXAMPLE.TEST./",
        "https://STAGING.EXAMPLE.TEST./healthz",
        "https://STAGING.EXAMPLE.TEST./livez",
    ]
    assert "renewal verified" in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["renew", "curl"])
def test_recover_propagates_command_failures(monkeypatch, failure):
    monkeypatch.setattr(MODULE.shutil, "which", lambda _name: "/usr/bin/cmctl")
    report = {
        "certificate": {
            "dnsNames": ["staging.example.test"],
            "revision": 1,
            "notAfter": "old",
            "ready": "True",
            "secret": {"present": True},
        }
    }
    after = {"certificate": {**report["certificate"], "revision": 2}}
    monkeypatch.setattr(MODULE, "verify_authorization", lambda *_args: report)
    monkeypatch.setattr(MODULE, "inventory", lambda *_args: after)
    monkeypatch.setattr(MODULE.time, "monotonic", lambda: 0)

    def fake_run(command, **_kwargs):
        failed = (failure == "renew" and command[0] == "cmctl") or (
            failure == "curl" and command[0] == "curl"
        )
        return subprocess.CompletedProcess(
            command,
            int(failed),
            b"",
            b"Bear" + b"er command-marker" if failed else b"",
        )

    monkeypatch.setattr(MODULE, "run", fake_run)
    expected = "cmctl renew failed" if failure == "renew" else "external HTTPS check failed"
    with pytest.raises(MODULE.OperationError, match=expected) as caught:
        MODULE.recover("example", "site-tls", "staging.example.test", 60)
    assert "command-marker" not in str(caught.value)


@pytest.mark.parametrize(
    "argv,called",
    [
        (["tool", "status", "--namespace", "ns", "--certificate", "cert"], "status"),
        (
            ["tool", "verify-authorization", "--namespace", "ns", "--certificate", "cert"],
            "verify",
        ),
        (["tool", "install-token"], "install"),
        (
            [
                "tool",
                "recover",
                "--namespace",
                "ns",
                "--certificate",
                "cert",
                "--host",
                "staging.example.test",
                "--timeout",
                "7",
            ],
            "recover",
        ),
    ],
)
def test_main_routes_subcommands(monkeypatch, argv, called):
    calls = []
    monkeypatch.setattr(MODULE.sys, "argv", argv)
    monkeypatch.setattr(MODULE, "staging_guard", lambda: calls.append("guard"))
    monkeypatch.setattr(MODULE, "inventory", lambda *args: calls.append(("status", args)) or {})
    monkeypatch.setattr(
        MODULE, "verify_authorization", lambda *args: calls.append(("verify", args))
    )
    monkeypatch.setattr(MODULE, "install_token", lambda: calls.append(("install", ())))
    monkeypatch.setattr(MODULE, "recover", lambda *args: calls.append(("recover", args)))

    assert MODULE.main() == 0
    assert any(isinstance(call, tuple) and call[0] == called for call in calls)


def test_main_redacts_operation_errors(monkeypatch, capsys):
    monkeypatch.setattr(MODULE.sys, "argv", ["tool", "install-token"])
    monkeypatch.setattr(
        MODULE,
        "install_token",
        lambda: (_ for _ in ()).throw(MODULE.OperationError("pass" + "word=visible-value")),
    )

    assert MODULE.main() == 1
    error = capsys.readouterr().err
    assert "visible-value" not in error
    assert "<redacted>" in error


def test_recover_missing_cmctl_fails_before_authorization_or_subprocess(monkeypatch):
    monkeypatch.setattr(MODULE.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        MODULE,
        "verify_authorization",
        lambda *_args: pytest.fail("missing cmctl must fail before cluster authorization"),
    )
    monkeypatch.setattr(
        MODULE, "run", lambda *_args, **_kwargs: pytest.fail("no subprocess may be started")
    )

    with pytest.raises(MODULE.OperationError) as exc_info:
        MODULE.recover("example", "site-tls", "staging.example.test", 60)
    assert "cmctl is required" in str(exc_info.value)
    assert "command -v cmctl" in str(exc_info.value)
    assert "cmctl version --client" in str(exc_info.value)


def test_main_reports_missing_cmctl_without_traceback(monkeypatch, capsys):
    monkeypatch.setattr(
        MODULE.sys,
        "argv",
        [
            "tool",
            "recover",
            "--namespace",
            "example",
            "--certificate",
            "site-tls",
            "--host",
            "staging.example.test",
        ],
    )
    monkeypatch.setattr(MODULE.shutil, "which", lambda _name: None)

    assert MODULE.main() == 1
    error = capsys.readouterr().err
    assert "cmctl is required" in error
    assert "command -v cmctl" in error
    assert "cmctl version --client" in error
    assert "Traceback" not in error
