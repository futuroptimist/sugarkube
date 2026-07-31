#!/usr/bin/env python3
"""Fail-closed, redacted cert-manager operations for the staging cluster."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any

STAGING_CONTEXT = "sugar-staging"
TOKEN_SECRET_NAMESPACE = "cert-manager"
TOKEN_SECRET_NAME = "cloudflare-api-token"
TOKEN_SECRET_KEY = "api-token"
REDACT = re.compile(
    r"(?i)\b(authorization\s*[:=]?\s*bearer|bearer|api[-_ ]?(?:token|key)|credential|pass"
    r"word|secret)"
    r"(\s*[:=]?\s+|\s*[:=]\s*)[^\s,;]+"
)
AUTHORIZATION_BLOCKERS = (
    (
        re.compile(r"(?:error\s*:\s*)?9109\b|invalid access token", re.IGNORECASE),
        "invalid credentials",
    ),
    (
        re.compile(r"(?:error\s*:\s*)?10502\b|too many authentication failures", re.IGNORECASE),
        "authentication throttling",
    ),
    (re.compile(r"found no zones", re.IGNORECASE), "zone authorization"),
)


class OperationError(RuntimeError):
    pass


def run(command: list[str], *, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def kubectl_command(args: list[str]) -> list[str]:
    return ["kubectl", "--context", STAGING_CONTEXT, *args]


def kubectl_json(args: list[str]) -> dict[str, Any]:
    result = run(kubectl_command([*args, "-o", "json"]))
    if result.returncode:
        raise OperationError(
            "kubectl failed: " + safe_message(result.stderr.decode(errors="replace"))
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise OperationError("kubectl returned invalid JSON") from error


def secret_present(namespace: str, name: str) -> bool:
    result = run(
        kubectl_command(
            ["-n", namespace, "get", "secret", name, "--ignore-not-found=true", "-o", "name"]
        )
    )
    if result.returncode:
        detail = safe_message(result.stderr.decode(errors="replace")).strip()
        message = "kubectl failed while checking Secret"
        raise OperationError(f"{message}: {detail}" if detail else message)
    return bool(result.stdout.strip())


def staging_guard() -> None:
    if os.environ.get("SUGARKUBE_ENV") != "staging":
        raise OperationError("refusing operation: export SUGARKUBE_ENV=staging")
    result = run(["kubectl", "config", "current-context"])
    context = result.stdout.decode(errors="replace").strip()
    if result.returncode or context != STAGING_CONTEXT:
        raise OperationError(
            f"refusing kubectl context: expected {STAGING_CONTEXT!r}, got {context or '(unavailable)'!r}"
        )


def condition(resource: dict[str, Any], kind: str = "Ready") -> dict[str, Any]:
    return next(
        (
            item
            for item in resource.get("status", {}).get("conditions", [])
            if item.get("type") == kind
        ),
        {},
    )


def safe_message(value: Any) -> str:
    return REDACT.sub(lambda match: f"{match.group(1)} <redacted>", str(value or ""))


def owner_name(resource: dict[str, Any], kinds: set[str]) -> str | None:
    for owner in resource.get("metadata", {}).get("ownerReferences", []):
        if owner.get("kind") in kinds:
            return owner.get("name")
    return None


def resource_state(resource: dict[str, Any]) -> dict[str, Any]:
    status = resource.get("status", {})
    ready = condition(resource)
    return {
        "name": resource.get("metadata", {}).get("name"),
        "state": status.get("state") or ready.get("status") or "Unknown",
        "reason": safe_message(ready.get("reason") or status.get("reason")),
        "message": safe_message(ready.get("message") or status.get("message")),
    }


def inventory(namespace: str, certificate_name: str) -> dict[str, Any]:
    certificate = kubectl_json(["-n", namespace, "get", "certificate", certificate_name])
    spec = certificate.get("spec", {})
    issuer_ref = spec.get("issuerRef") or {}
    if not issuer_ref.get("name"):
        raise OperationError("Certificate has no issuerRef.name")
    issuer_kind = issuer_ref.get("kind", "Issuer")
    issuer_args = ["get", "clusterissuer" if issuer_kind == "ClusterIssuer" else "issuer"]
    if issuer_kind != "ClusterIssuer":
        issuer_args[:0] = ["-n", namespace]
    issuer = kubectl_json([*issuer_args, issuer_ref["name"]])
    token_refs = []
    for solver in issuer.get("spec", {}).get("acme", {}).get("solvers", []):
        ref = solver.get("dns01", {}).get("cloudflare", {}).get("apiTokenSecretRef")
        if ref:
            token_refs.append({"name": ref.get("name"), "key": ref.get("key")})
    requests = kubectl_json(["-n", namespace, "get", "certificaterequests"]).get("items", [])
    requests = [item for item in requests if owner_name(item, {"Certificate"}) == certificate_name]
    request_names = {item.get("metadata", {}).get("name") for item in requests}
    orders = kubectl_json(["-n", namespace, "get", "orders"]).get("items", [])
    orders = [item for item in orders if owner_name(item, {"CertificateRequest"}) in request_names]
    order_names = {item.get("metadata", {}).get("name") for item in orders}
    challenges = kubectl_json(["-n", namespace, "get", "challenges"]).get("items", [])
    challenges = [item for item in challenges if owner_name(item, {"Order"}) in order_names]

    secret_name = spec.get("secretName")
    serving_secret_present = False
    if secret_name:
        serving_secret_present = secret_present(namespace, secret_name)

    related = {
        ("Certificate", certificate_name),
        *(("CertificateRequest", item.get("metadata", {}).get("name")) for item in requests),
        *(("Order", item.get("metadata", {}).get("name")) for item in orders),
        *(("Challenge", item.get("metadata", {}).get("name")) for item in challenges),
    }
    events = kubectl_json(["-n", namespace, "get", "events"]).get("items", [])
    events = [
        item
        for item in events
        if (item.get("involvedObject", {}).get("kind"), item.get("involvedObject", {}).get("name"))
        in related
    ]
    ready = condition(certificate)
    expected_ref = {"name": TOKEN_SECRET_NAME, "key": TOKEN_SECRET_KEY}
    return {
        "certificate": {
            "namespace": namespace,
            "name": certificate_name,
            "dnsNames": spec.get("dnsNames", []),
            "ready": ready.get("status", "Unknown"),
            "reason": safe_message(ready.get("reason")),
            "notBefore": certificate.get("status", {}).get("notBefore"),
            "notAfter": certificate.get("status", {}).get("notAfter"),
            "renewalTime": certificate.get("status", {}).get("renewalTime"),
            "revision": certificate.get("status", {}).get("revision"),
            "secret": {"name": secret_name, "present": serving_secret_present},
        },
        "issuer": {
            "name": issuer_ref["name"],
            "kind": issuer_kind,
            "ready": condition(issuer).get("status", "Unknown"),
            "reason": safe_message(condition(issuer).get("reason")),
            "cloudflareTokenSecretRefs": token_refs,
            "expectedTokenSecretRefConfigured": expected_ref in token_refs,
        },
        "certificateRequests": [resource_state(item) for item in requests],
        "orders": [resource_state(item) for item in orders],
        "challenges": [
            {
                **resource_state(item),
                "dnsName": item.get("spec", {}).get("dnsName"),
                "active": item.get("status", {}).get("state")
                not in {"valid", "expired", "invalid"},
            }
            for item in challenges
        ],
        "events": [
            {
                "object": item.get("involvedObject", {}).get("kind"),
                "name": item.get("involvedObject", {}).get("name"),
                "type": item.get("type"),
                "reason": safe_message(item.get("reason")),
                "message": safe_message(item.get("message")),
            }
            for item in events[-40:]
        ],
    }


def verify_authorization(namespace: str, certificate_name: str) -> dict[str, Any]:
    staging_guard()
    report = inventory(namespace, certificate_name)
    if report["issuer"]["ready"] != "True":
        raise OperationError("referenced issuer is not Ready=True")
    if not report["issuer"]["expectedTokenSecretRefConfigured"]:
        raise OperationError(
            f"Cloudflare solver must reference {TOKEN_SECRET_NAMESPACE}/{TOKEN_SECRET_NAME} key {TOKEN_SECRET_KEY}"
        )
    exists = run(
        kubectl_command(
            ["-n", TOKEN_SECRET_NAMESPACE, "get", "secret", TOKEN_SECRET_NAME, "-o", "name"]
        )
    )
    if exists.returncode:
        raise OperationError(
            f"required Secret {TOKEN_SECRET_NAMESPACE}/{TOKEN_SECRET_NAME} is missing or inaccessible"
        )
    for challenge in report["challenges"]:
        detail = f"{challenge['reason']} {challenge['message']}"
        if challenge["active"]:
            for pattern, blocker in AUTHORIZATION_BLOCKERS:
                if pattern.search(detail):
                    raise OperationError(
                        f"active Challenge has a Cloudflare {blocker} blocker; "
                        "stop retries and resolve it before renewal"
                    )
    print(
        "authorization structure verified; a successful DNS-01 Challenge is still required to prove dashboard scope"
    )
    return report


def install_token() -> None:
    staging_guard()
    credential = (
        getpass.getpass("Cloudflare credential (hidden input): ").encode()
        if sys.stdin.isatty()
        else sys.stdin.buffer.read()
    )
    credential = credential.strip()
    if (
        not credential
        or any(byte in b" \t\r\n\v\f" for byte in credential)
        or credential[:1] in {b"'", b'"'}
        or credential[-1:] in {b"'", b'"'}
    ):
        raise OperationError("token input is empty or malformed")
    create = subprocess.Popen(
        kubectl_command(
            [
                "-n",
                TOKEN_SECRET_NAMESPACE,
                "create",
                "secret",
                "generic",
                TOKEN_SECRET_NAME,
                f"--from-file={TOKEN_SECRET_KEY}=/dev/stdin",
                "--dry-run=client",
                "-o",
                "yaml",
            ]
        ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    apply = subprocess.Popen(
        kubectl_command(["apply", "-f", "-"]),
        stdin=create.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert create.stdin is not None and create.stdout is not None
    create.stdout.close()
    create.stdin.write(credential)
    create.stdin.close()
    _, apply_stderr = apply.communicate()
    create_stderr = create.stderr.read() if create.stderr else b""
    create_code = create.wait()
    del credential
    if create_code or apply.returncode:
        raise OperationError(
            "Secret installation failed (credential output suppressed): "
            + safe_message((create_stderr + apply_stderr).decode(errors="replace"))
        )
    print(f"{TOKEN_SECRET_NAME} installed; Secret value was not displayed")


def recover(namespace: str, certificate_name: str, host: str, timeout: int) -> None:
    if shutil.which("cmctl") is None:
        raise OperationError(
            "cmctl is required for recovery; install it and verify with "
            "'command -v cmctl' and 'cmctl version --client'"
        )
    report = verify_authorization(namespace, certificate_name)
    normalized_host = host.rstrip(".").lower()
    dns_names = {
        str(name).rstrip(".").lower() for name in report["certificate"].get("dnsNames", [])
    }
    if normalized_host not in dns_names:
        raise OperationError(f"verification host {host!r} is not listed in Certificate DNS names")
    result = run(
        ["cmctl", "--context", STAGING_CONTEXT, "renew", "-n", namespace, certificate_name]
    )
    if result.returncode:
        raise OperationError(
            "cmctl renew failed: " + safe_message(result.stderr.decode(errors="replace"))
        )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        after = inventory(namespace, certificate_name)
        old, new = report["certificate"], after["certificate"]
        changed = new["revision"] != old["revision"] or new["notAfter"] != old["notAfter"]
        if new["ready"] == "True" and new["secret"]["present"] and changed:
            break
        time.sleep(5)
    else:
        raise OperationError(
            "bounded wait expired before Ready=True, Secret presence, and revision/expiry change"
        )
    for path in ("/", "/healthz", "/livez"):
        check = run(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--max-time",
                "15",
                f"https://{host}{path}",
            ]
        )
        if check.returncode:
            raise OperationError(f"external HTTPS check failed for {path}")
    print(json.dumps(after, indent=2, sort_keys=True))
    print("renewal verified: Ready, Secret, revision/expiry change, and HTTPS paths")


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "verify-authorization"):
        command = commands.add_parser(name)
        command.add_argument("--namespace", required=True)
        command.add_argument("--certificate", required=True)
    commands.add_parser("install-token")
    recovery = commands.add_parser("recover")
    recovery.add_argument("--namespace", required=True)
    recovery.add_argument("--certificate", required=True)
    recovery.add_argument("--host", required=True)
    recovery.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    try:
        if args.command == "status":
            staging_guard()
            print(json.dumps(inventory(args.namespace, args.certificate), indent=2, sort_keys=True))
        elif args.command == "verify-authorization":
            verify_authorization(args.namespace, args.certificate)
        elif args.command == "install-token":
            install_token()
        else:
            recover(args.namespace, args.certificate, args.host, args.timeout)
    except OperationError as error:
        print(f"ERROR: {safe_message(error)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
