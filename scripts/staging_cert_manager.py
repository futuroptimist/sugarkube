#!/usr/bin/env python3
"""Guarded, redacted cert-manager staging operations.

The program deliberately reads only Kubernetes resource metadata and status.  It never
requests Secret data and accepts the Cloudflare token only from a TTY or standard input.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import time
from typing import Any

REDACT = re.compile(
    r"(?i)(api[-_ ]?token|secret)(\s*[:=]\s*|\s+)[^\s,;]+"
    r"|(?i:(authorization\s*[:=]?\s*bearer|bearer))\s+[^\s,;]+"
)


class OperationError(RuntimeError):
    pass


def run(command: list[str], *, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def kubectl_json(args: list[str]) -> dict[str, Any]:
    result = run(["kubectl", *args, "-o", "json"])
    if result.returncode:
        raise OperationError(result.stderr.decode(errors="replace").strip())
    return json.loads(result.stdout)


def staging_guard() -> None:
    if os.environ.get("SUGARKUBE_ENV") != "staging":
        raise OperationError("refusing operation: export SUGARKUBE_ENV=staging")
    result = run(["kubectl", "config", "current-context"])
    context = result.stdout.decode(errors="replace").strip()
    if result.returncode or "staging" not in context.lower():
        raise OperationError(f"refusing non-staging kubectl context: {context or '(unavailable)'}")


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
    text = str(value or "")
    return REDACT.sub(lambda match: f"{match.group(1) or match.group(3)}<redacted>", text)


def owner_name(resource: dict[str, Any], kinds: set[str]) -> str | None:
    for owner in resource.get("metadata", {}).get("ownerReferences", []):
        if owner.get("kind") in kinds:
            return owner.get("name")
    return None


def inventory(namespace: str, certificate_name: str) -> dict[str, Any]:
    certificate = kubectl_json(["-n", namespace, "get", "certificate", certificate_name])
    spec = certificate.get("spec", {})
    issuer_ref = spec.get("issuerRef") or {}
    if not issuer_ref.get("name"):
        raise OperationError("Certificate has no issuerRef.name")
    issuer_kind = issuer_ref.get("kind", "Issuer")
    issuer_args = ["get", "clusterissuer" if issuer_kind == "ClusterIssuer" else "issuer"]
    if issuer_kind != "ClusterIssuer":
        issuer_args[0:0] = ["-n", namespace]
    issuer = kubectl_json([*issuer_args, issuer_ref["name"]])
    token_refs = []
    for solver in issuer.get("spec", {}).get("acme", {}).get("solvers", []):
        token_ref = solver.get("dns01", {}).get("cloudflare", {}).get("apiTokenSecretRef")
        if token_ref:
            token_refs.append({"name": token_ref.get("name"), "key": token_ref.get("key")})
    requests = kubectl_json(["-n", namespace, "get", "certificaterequests"]).get("items", [])
    requests = [r for r in requests if owner_name(r, {"Certificate"}) == certificate_name]
    request_names = {r.get("metadata", {}).get("name") for r in requests}
    orders = kubectl_json(["-n", namespace, "get", "orders"]).get("items", [])
    orders = [o for o in orders if owner_name(o, {"CertificateRequest"}) in request_names]
    order_names = {o.get("metadata", {}).get("name") for o in orders}
    challenges = kubectl_json(["-n", namespace, "get", "challenges"]).get("items", [])
    challenges = [c for c in challenges if owner_name(c, {"Order"}) in order_names]
    secret_name = spec.get("secretName")
    secret_present = False
    if secret_name:
        secret_result = run(
            ["kubectl", "-n", namespace, "get", "secret", secret_name, "-o", "name"]
        )
        secret_present = secret_result.returncode == 0
    events = kubectl_json(
        [
            "-n",
            namespace,
            "get",
            "events",
            "--field-selector",
            f"involvedObject.name={certificate_name}",
        ]
    ).get("items", [])
    ready = condition(certificate)

    def state(resource: dict[str, Any]) -> dict[str, Any]:
        status = resource.get("status", {})
        ready_condition = condition(resource)
        return {
            "name": resource.get("metadata", {}).get("name"),
            "state": status.get("state") or ready_condition.get("status") or "Unknown",
            "reason": safe_message(ready_condition.get("reason") or status.get("reason")),
            "message": safe_message(ready_condition.get("message") or status.get("message")),
        }

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
            "secret": {"name": secret_name, "present": secret_present},
        },
        "issuer": {
            "name": issuer_ref["name"],
            "kind": issuer_kind,
            "ready": condition(issuer).get("status", "Unknown"),
            "reason": safe_message(condition(issuer).get("reason")),
            "cloudflareTokenSecretRefs": token_refs,
            "expectedTokenSecretRefConfigured": {
                "name": "cloudflare-api-token",
                "key": "api-token",
            }
            in token_refs,
        },
        "certificateRequests": [state(item) for item in requests],
        "orders": [state(item) for item in orders],
        "challenges": [
            {
                **state(item),
                "dnsName": item.get("spec", {}).get("dnsName"),
                "active": not bool(
                    item.get("status", {}).get("state") in {"valid", "expired", "invalid"}
                ),
            }
            for item in challenges
        ],
        "events": [
            {
                "type": item.get("type"),
                "reason": safe_message(item.get("reason")),
                "message": safe_message(item.get("message")),
            }
            for item in events[-10:]
        ],
    }


def install_token() -> None:
    staging_guard()
    credential = (
        getpass.getpass("Cloudflare credential (hidden input): ").encode()
        if sys.stdin.isatty()
        else sys.stdin.buffer.read()
    )
    credential = credential.strip()
    if not credential or b"\n" in credential or b"\r" in credential:
        raise OperationError("token input is empty or malformed")
    create = subprocess.Popen(
        [
            "kubectl",
            "-n",
            "cert-manager",
            "create",
            "secret",
            "generic",
            "cloudflare-api-token",
            "--from-file=api-token=/dev/stdin",
            "--dry-run=client",
            "-o",
            "yaml",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    apply = subprocess.Popen(
        ["kubectl", "apply", "-f", "-"],
        stdin=create.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert create.stdin is not None and create.stdout is not None
    create.stdout.close()
    create.stdin.write(credential)
    create.stdin.close()
    _apply_stdout, apply_stderr = apply.communicate()
    create_stderr = create.stderr.read() if create.stderr else b""
    create_code = create.wait()
    del credential
    if create_code or apply.returncode:
        raise OperationError(
            "Secret installation failed (credential output suppressed): "
            + safe_message((create_stderr + apply_stderr).decode(errors="replace"))
        )
    print("cloudflare-api-token installed; Secret value was not displayed")


def recover(namespace: str, certificate_name: str, host: str, timeout: int) -> None:
    staging_guard()
    before = inventory(namespace, certificate_name)
    normalized_host = host.rstrip(".").lower()
    dns_names = {
        str(name).rstrip(".").lower() for name in before["certificate"].get("dnsNames", [])
    }
    if normalized_host not in dns_names:
        raise OperationError(f"verification host {host!r} is not listed in Certificate DNS names")
    result = run(["cmctl", "renew", "-n", namespace, certificate_name])
    if result.returncode:
        raise OperationError(
            "cmctl renew failed: " + safe_message(result.stderr.decode(errors="replace"))
        )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        after = inventory(namespace, certificate_name)
        old = before["certificate"]
        new = after["certificate"]
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
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("status")
    status.add_argument("--namespace", required=True)
    status.add_argument("--certificate", required=True)
    subparsers.add_parser("install-token")
    recovery = subparsers.add_parser("recover")
    recovery.add_argument("--namespace", required=True)
    recovery.add_argument("--certificate", required=True)
    recovery.add_argument("--host", required=True)
    recovery.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    try:
        if args.command == "status":
            staging_guard()
            print(json.dumps(inventory(args.namespace, args.certificate), indent=2, sort_keys=True))
        elif args.command == "install-token":
            install_token()
        else:
            recover(args.namespace, args.certificate, args.host, args.timeout)
    except (OperationError, json.JSONDecodeError) as error:
        print(f"ERROR: {safe_message(error)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
