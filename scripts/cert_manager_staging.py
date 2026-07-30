#!/usr/bin/env python3
"""Guarded, redacted cert-manager operations for the staging cluster."""

from __future__ import annotations

import argparse
import getpass
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

CONTEXT = "sugar-staging"
SECRET_NAMESPACE = "cert-manager"
SECRET_NAME = "cloudflare-api-token"
SECRET_KEY = "api-token"
REDACT = re.compile(r"(?i)\b(api[_-]?token|authorization|bearer|secret)\b.*")


def safe(value: Any) -> str:
    """Make controller messages safe for terminals and CI logs."""
    return REDACT.sub(r"\1=[REDACTED]", str(value or "").replace("\n", " "))


def run(
    args: list[str], *, data: bytes | None = None, capture: bool = True
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        args,
        input=data,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE,
        check=False,
    )


def kubectl(*args: str, check: bool = True) -> bytes:
    result = run(["kubectl", "--context", CONTEXT, *args])
    if check and result.returncode:
        raise RuntimeError(safe(result.stderr.decode(errors="replace")))
    return result.stdout


def assert_staging() -> None:
    current = kubectl("config", "current-context").decode().strip()
    if current != CONTEXT:
        raise RuntimeError(
            f"refusing cluster access: current context must be {CONTEXT}, got {current or '<none>'}"
        )
    nodes = json.loads(kubectl("get", "nodes", "-o", "json"))
    envs = {
        item.get("metadata", {}).get("labels", {}).get("sugarkube.env")
        for item in nodes.get("items", [])
    }
    if envs != {"staging"}:
        raise RuntimeError(
            "refusing cluster access: node sugarkube.env labels must be exactly staging, "
            f"got {safe(envs)}"
        )


def objects(resource: str) -> list[dict[str, Any]]:
    return json.loads(kubectl("get", resource, "--all-namespaces", "-o", "json")).get(
        "items", []
    )


def condition(item: dict[str, Any]) -> tuple[str, str, str]:
    conditions = item.get("status", {}).get("conditions", [])
    ready = next((c for c in conditions if c.get("type") == "Ready"), {})
    return (
        safe(ready.get("status", "Unknown")),
        safe(ready.get("reason", "-")),
        safe(ready.get("message", "-")),
    )


def owner_names(item: dict[str, Any]) -> set[str]:
    return {
        o.get("name", "") for o in item.get("metadata", {}).get("ownerReferences", [])
    }


def active_challenges(data: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    certificate_names = {
        item.get("metadata", {}).get("name", "") for item in data["certificates"]
    }
    request_names = {
        item.get("metadata", {}).get("name", "")
        for item in data["certificaterequests"]
        if owner_names(item) & certificate_names
    }
    order_names = {
        item.get("metadata", {}).get("name", "")
        for item in data["orders"]
        if owner_names(item) & request_names
    }
    return [
        item
        for item in data["challenges"]
        if owner_names(item) & order_names
        and item.get("status", {}).get("state") != "valid"
    ]


def render_status(data: dict[str, list[dict[str, Any]]], secret_present: bool) -> str:
    lines = [
        f"Cloudflare Secret: {SECRET_NAMESPACE}/{SECRET_NAME} key={SECRET_KEY} "
        f"present={'yes' if secret_present else 'no'}"
    ]
    requests, orders, challenges = (
        data["certificaterequests"],
        data["orders"],
        data["challenges"],
    )
    for issuer in sorted(
        data.get("clusterissuers", []), key=lambda x: x["metadata"].get("name", "")
    ):
        ready, reason, message = condition(issuer)
        refs = []
        for solver in issuer.get("spec", {}).get("acme", {}).get("solvers", []):
            ref = (
                solver.get("dns01", {})
                .get("cloudflare", {})
                .get("apiTokenSecretRef", {})
            )
            if ref:
                refs.append(
                    f"{ref.get('name', '<missing>')}/{ref.get('key', '<missing>')}"
                )
        lines.append(
            f"Issuer: ClusterIssuer/{issuer['metadata'].get('name')} Ready={ready} reason={reason} "
            f"message={message} CloudflareSecret={','.join(refs) or '-'}"
        )
    for cert in sorted(
        data["certificates"],
        key=lambda x: (
            x["metadata"].get("namespace", ""),
            x["metadata"].get("name", ""),
        ),
    ):
        meta, spec, status = (
            cert["metadata"],
            cert.get("spec", {}),
            cert.get("status", {}),
        )
        ns, name = meta.get("namespace", ""), meta.get("name", "")
        ready, reason, message = condition(cert)
        issuer = spec.get("issuerRef", {})
        lines += [
            "",
            f"Certificate: {ns}/{name}",
            f"  Ready: {ready} reason={reason} message={message}",
            f"  issuer: {issuer.get('kind', 'Issuer')}/{issuer.get('name', '<missing>')}",
            f"  Secret: {ns}/{spec.get('secretName', '<missing>')} "
            f"present={'yes' if cert.get('_secretPresent') else 'no'}",
            f"  revision: {status.get('revision', '-')} "
            f"notBefore={status.get('notBefore', '-')} notAfter={status.get('notAfter', '-')} "
            f"renewalTime={status.get('renewalTime', '-')}",
            f"  DNS names: {', '.join(spec.get('dnsNames', [])) or '-'}",
        ]
        related_req = [
            r
            for r in requests
            if r.get("metadata", {}).get("namespace") == ns and name in owner_names(r)
        ]
        req_names = {r.get("metadata", {}).get("name", "") for r in related_req}
        related_orders = [
            o
            for o in orders
            if o.get("metadata", {}).get("namespace") == ns
            and owner_names(o) & req_names
        ]
        order_names = {o.get("metadata", {}).get("name", "") for o in related_orders}
        related_challenges = [
            c
            for c in challenges
            if c.get("metadata", {}).get("namespace") == ns
            and owner_names(c) & order_names
        ]
        for label, items in (
            ("CertificateRequest", related_req),
            ("Order", related_orders),
            ("Challenge", related_challenges),
        ):
            if not items:
                lines.append(f"  {label}: none")
            for item in items:
                state, why, msg = (
                    condition(item)
                    if label == "CertificateRequest"
                    else (
                        safe(item.get("status", {}).get("state", "pending")),
                        safe(item.get("status", {}).get("reason", "-")),
                        safe(item.get("status", {}).get("message", "-")),
                    )
                )
                lines.append(
                    f"  {label}: {item['metadata'].get('name')} state={state} "
                    f"reason={why} message={msg}"
                )
    for event in data.get("events", []):
        involved = event.get("involvedObject", {})
        if involved.get("apiVersion", "").startswith(
            ("cert-manager.io/", "acme.cert-manager.io/")
        ):
            lines.append(
                f"Event: {involved.get('namespace', '-')}/{involved.get('kind', '-')}/"
                f"{involved.get('name', '-')} reason={safe(event.get('reason'))} "
                f"message={safe(event.get('message'))}"
            )
    return "\n".join(lines) + "\n"


def status() -> int:
    data = {
        name: objects(name)
        for name in (
            "clusterissuers",
            "certificates",
            "certificaterequests",
            "orders",
            "challenges",
            "events",
        )
    }
    for cert in data["certificates"]:
        namespace = cert.get("metadata", {}).get("namespace", "")
        secret_name = cert.get("spec", {}).get("secretName", "")
        result = run(
            [
                "kubectl",
                "--context",
                CONTEXT,
                "-n",
                namespace,
                "get",
                "secret",
                secret_name,
                "--request-timeout=15s",
                "-o",
                "name",
            ]
        )
        cert["_secretPresent"] = bool(secret_name and result.returncode == 0)
    secret = run(
        [
            "kubectl",
            "--context",
            CONTEXT,
            "-n",
            SECRET_NAMESPACE,
            "get",
            "secret",
            SECRET_NAME,
            "--request-timeout=15s",
            "-o",
            "name",
        ]
    )
    print(render_status(data, secret.returncode == 0), end="")
    return (
        1
        if any(
            "Found no Zones" in str(c.get("status", {}))
            for c in active_challenges(data)
        )
        else 0
    )


def install_token(path: str | None) -> int:
    if path:
        credential = Path(path).read_bytes().rstrip(b"\r\n")
    elif sys.stdin.isatty():
        credential = getpass.getpass("Cloudflare API credential: ").encode()
    else:
        credential = sys.stdin.buffer.read().rstrip(b"\r\n")
    if not credential:
        raise RuntimeError("Cloudflare API token input is empty")
    rendered = run(
        [
            "kubectl",
            "--context",
            CONTEXT,
            "-n",
            SECRET_NAMESPACE,
            "create",
            "secret",
            "generic",
            SECRET_NAME,
            f"--from-file={SECRET_KEY}=/dev/stdin",
            "--dry-run=client",
            "-o",
            "yaml",
        ],
        data=credential,
    )
    credential = b""  # discard the clear-text reference before applying
    if rendered.returncode:
        raise RuntimeError(safe(rendered.stderr.decode(errors="replace")))
    applied = run(
        ["kubectl", "--context", CONTEXT, "apply", "-f", "-"], data=rendered.stdout
    )
    if applied.returncode:
        raise RuntimeError(safe(applied.stderr.decode(errors="replace")))
    print(f"Updated {SECRET_NAMESPACE}/{SECRET_NAME}; token value was not displayed.")
    return 0


def renew(namespace: str, certificate: str, hostname: str, timeout: int) -> int:
    before = json.loads(
        kubectl("-n", namespace, "get", "certificate", certificate, "-o", "json")
    )
    result = run(["cmctl", "--context", CONTEXT, "renew", "-n", namespace, certificate])
    if result.returncode:
        raise RuntimeError(safe(result.stderr.decode(errors="replace")))
    wait = run(
        [
            "kubectl",
            "--context",
            CONTEXT,
            "-n",
            namespace,
            "wait",
            "--for=condition=Ready",
            f"certificate/{certificate}",
            f"--timeout={timeout}s",
        ]
    )
    if wait.returncode:
        raise RuntimeError(
            f"bounded Ready wait failed: {safe(wait.stderr.decode(errors='replace'))}"
        )
    after = json.loads(
        kubectl("-n", namespace, "get", "certificate", certificate, "-o", "json")
    )
    old, new = before.get("status", {}), after.get("status", {})
    changed = old.get("revision") != new.get("revision") or old.get(
        "notAfter"
    ) != new.get("notAfter")
    if not changed:
        raise RuntimeError(
            "Certificate became Ready but neither revision nor expiry changed; "
            "stop before another renewal"
        )
    for path in ("/", "/healthz", "/livez"):
        probe = run(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--max-time",
                "15",
                f"https://{hostname}{path}",
            ]
        )
        if probe.returncode:
            raise RuntimeError(
                f"external HTTPS verification failed for {hostname}{path}: "
                f"{safe(probe.stderr.decode(errors='replace'))}"
            )
    print(
        f"Renewed {namespace}/{certificate}: revision/expiry changed and HTTPS checks "
        f"passed for {hostname}."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    install = sub.add_parser("install-token")
    install.add_argument("--file")
    renewal = sub.add_parser("renew")
    renewal.add_argument("--namespace", required=True)
    renewal.add_argument("--certificate", required=True)
    renewal.add_argument("--hostname", required=True)
    renewal.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    assert_staging()
    if args.action == "status":
        return status()
    if args.action == "install-token":
        return install_token(args.file)
    if not 30 <= args.timeout <= 600:
        raise RuntimeError("timeout must be between 30 and 600 seconds")
    return renew(args.namespace, args.certificate, args.hostname, args.timeout)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {safe(exc)}", file=sys.stderr)
        raise SystemExit(2)
