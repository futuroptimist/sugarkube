#!/usr/bin/env python3
"""Guarded, redacted cert-manager staging operations."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
from typing import Any

CONTEXT = "sugar-staging"
SECRET_NAMESPACE = "cert-manager"
SECRET_NAME = "cloudflare-api-token"
SECRET_KEY = "api-token"
REDACT = re.compile(r"(?i)(api[-_ ]?token|authorization|bearer|secret)(\s*[:=]\s*)(\S+)")


def run(
    args: list[str], *, input_text: str | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, input=input_text, text=True, capture_output=True, check=check)


def kubectl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["kubectl", "--context", CONTEXT, *args], check=check)


def guard() -> None:
    env = os.environ.get("SUGARKUBE_ENV", "staging")
    if env != "staging":
        raise SystemExit("ERROR: this operation is staging-only (SUGARKUBE_ENV must be staging)")
    current = run(["kubectl", "config", "current-context"]).stdout.strip()
    if current != CONTEXT:
        raise SystemExit(f"ERROR: current kubectl context must be exactly {CONTEXT}")


def load(kind: str) -> list[dict[str, Any]]:
    result = kubectl("get", kind, "--all-namespaces", "-o", "json", check=False)
    if result.returncode:
        return []
    return json.loads(result.stdout).get("items", [])


def ref(obj: dict[str, Any]) -> str:
    meta = obj.get("metadata", {})
    return f"{meta.get('namespace', '-')}/{meta.get('name', '-')}"


def condition(obj: dict[str, Any], name: str = "Ready") -> tuple[str, str, str]:
    for item in obj.get("status", {}).get("conditions", []):
        if item.get("type") == name:
            return item.get("status", "Unknown"), item.get("reason", "-"), item.get("message", "-")
    return "Unknown", "MissingCondition", "-"


def safe(value: Any) -> str:
    text = str(value if value not in (None, "") else "-").replace("\n", " ")
    return REDACT.sub(r"\1\2[REDACTED]", text)


def selected(certs: list[dict[str, Any]], inventory: list[str]) -> list[dict[str, Any]]:
    if not inventory:
        return certs
    wanted = set(inventory)
    found = [cert for cert in certs if ref(cert) in wanted]
    missing = sorted(wanted - {ref(cert) for cert in found})
    if missing:
        print("Missing certificates: " + ", ".join(missing), file=sys.stderr)
    return found


def status(inventory: list[str]) -> int:
    certs = selected(load("certificates.cert-manager.io"), inventory)
    requests = load("certificaterequests.cert-manager.io")
    orders = load("orders.acme.cert-manager.io")
    challenges = load("challenges.acme.cert-manager.io")
    issuers = load("clusterissuers.cert-manager.io") + load("issuers.cert-manager.io")
    events = load("events")
    failures = 0
    for cert in certs:
        meta, spec, state = cert.get("metadata", {}), cert.get("spec", {}), cert.get("status", {})
        ready, reason, _ = condition(cert)
        issuer = spec.get("issuerRef", {})
        issuer_text = f"{issuer.get('kind', 'Issuer')}/{issuer.get('name', '-')}"
        secret = spec.get("secretName", "-")
        present = (
            kubectl(
                "-n", meta.get("namespace", ""), "get", "secret", secret, "-o", "name", check=False
            ).returncode
            == 0
        )
        print(f"Certificate: {ref(cert)}")
        print(f"  Ready: {ready} ({safe(reason)})")
        print(f"  issuer: {issuer_text}")
        print(f"  Secret present: {'yes' if present else 'no'} ({safe(secret)})")
        print(f"  revision: {safe(state.get('revision'))}")
        print(f"  notBefore: {safe(state.get('notBefore'))}")
        print(f"  expiry/notAfter: {safe(state.get('notAfter'))}")
        print(f"  renewalTime: {safe(state.get('renewalTime'))}")
        print(f"  DNS names: {', '.join(map(safe, spec.get('dnsNames', []))) or '-'}")
        owned_requests = [
            x
            for x in requests
            if x.get("metadata", {}).get("namespace") == meta.get("namespace")
            and any(
                owner.get("name") == meta.get("name")
                for owner in x.get("metadata", {}).get("ownerReferences", [])
            )
        ]
        print(
            "  CertificateRequests: "
            + (
                ", ".join(
                    f"{ref(x)}={condition(x)[0]}/{safe(condition(x)[1])}" for x in owned_requests
                )
                or "none"
            )
        )
        request_names = {x.get("metadata", {}).get("name") for x in owned_requests}
        owned_orders = [
            x
            for x in orders
            if x.get("metadata", {}).get("namespace") == meta.get("namespace")
            and any(
                o.get("name") in request_names
                for o in x.get("metadata", {}).get("ownerReferences", [])
            )
        ]
        print(
            "  Orders: "
            + (
                ", ".join(
                    f"{ref(x)}={safe(x.get('status', {}).get('state'))}" for x in owned_orders
                )
                or "none"
            )
        )
        order_names = {x.get("metadata", {}).get("name") for x in owned_orders}
        owned_challenges = [
            x
            for x in challenges
            if x.get("metadata", {}).get("namespace") == meta.get("namespace")
            and any(
                o.get("name") in order_names
                for o in x.get("metadata", {}).get("ownerReferences", [])
            )
        ]
        for challenge in owned_challenges:
            state_text = challenge.get("status", {}).get("state", "pending")
            challenge_reason = safe(challenge.get("status", {}).get("reason"))
            print(f"  Challenge: {ref(challenge)}={safe(state_text)} reason={challenge_reason}")
            if "Found no Zones" in str(challenge.get("status", {}).get("reason", "")):
                failures += 1
        related = [
            e
            for e in events
            if e.get("metadata", {}).get("namespace") == meta.get("namespace")
            and e.get("involvedObject", {}).get("name")
            in (
                {meta.get("name")}
                | request_names
                | order_names
                | {x.get("metadata", {}).get("name") for x in owned_challenges}
            )
        ]
        print(
            "  relevant events: "
            + (
                "; ".join(
                    f"{safe(e.get('reason'))}: {safe(e.get('message'))}" for e in related[-5:]
                )
                or "none"
            )
        )
        if ready != "True" or not present:
            failures += 1
    for issuer in issuers:
        ready, reason, _ = condition(issuer)
        print(f"Issuer: {ref(issuer)} Ready={ready} reason={safe(reason)}")
    return 1 if failures else 0


def install_token(path: str | None) -> None:
    guard()
    if path:
        with open(path, encoding="utf-8") as handle:
            credential = handle.read().strip()
    elif sys.stdin.isatty():
        credential = getpass.getpass("Cloudflare API token (hidden): ").strip()
    else:
        credential = sys.stdin.read().strip()
    if not credential or "\n" in credential or "\r" in credential:
        raise SystemExit("ERROR: token input must be one non-empty line")
    create = run(
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
        input_text=credential,
    )
    try:
        run(["kubectl", "--context", CONTEXT, "apply", "-f", "-"], input_text=create.stdout)
    finally:
        credential = ""
    print(f"Updated {SECRET_NAMESPACE}/{SECRET_NAME}; token value was not displayed.")


def verify_auth() -> None:
    guard()
    result = kubectl("-n", SECRET_NAMESPACE, "get", "secret", SECRET_NAME, "-o", "name")
    if not result.stdout.strip():
        raise SystemExit(f"ERROR: {SECRET_NAMESPACE}/{SECRET_NAME} is missing")
    issuer = kubectl("get", "clusterissuer", "letsencrypt-production", "-o", "json")
    obj = json.loads(issuer.stdout)
    if condition(obj)[0] != "True":
        raise SystemExit("ERROR: letsencrypt-production is not Ready")
    rendered = json.dumps(obj.get("spec", {}))
    if SECRET_NAME not in rendered or SECRET_KEY not in rendered:
        raise SystemExit("ERROR: issuer does not reference the expected Secret name/key")
    active_auth_errors = [
        ref(challenge)
        for challenge in load("challenges.acme.cert-manager.io")
        if challenge.get("status", {}).get("state") not in ("valid", "expired")
        and "Found no Zones" in str(challenge.get("status", {}).get("reason", ""))
    ]
    if active_auth_errors:
        raise SystemExit(
            "ERROR: active Challenges still report Cloudflare zone authorization failures: "
            + ", ".join(active_auth_errors)
        )
    print(
        "Authorization prerequisites verified: issuer Ready; expected Secret exists and issuer "
        "references its expected key (Secret data was not read)."
    )


def renew(certificate: str, hostname: str, timeout: str) -> None:
    guard()
    namespace, name = certificate.split("/", 1)
    before = json.loads(
        kubectl("-n", namespace, "get", "certificate", name, "-o", "json").stdout
    ).get("status", {})
    run(["cmctl", "--context", CONTEXT, "renew", "-n", namespace, name])
    kubectl(
        "-n",
        namespace,
        "wait",
        "--for=condition=Ready",
        f"certificate/{name}",
        f"--timeout={timeout}",
    )
    after = json.loads(
        kubectl("-n", namespace, "get", "certificate", name, "-o", "json").stdout
    ).get("status", {})
    if before.get("revision") == after.get("revision") and before.get("notAfter") == after.get(
        "notAfter"
    ):
        raise SystemExit("ERROR: Ready returned but neither revision nor expiry changed")
    for path in ("/", "/healthz", "/livez"):
        run(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--max-time",
                "15",
                f"https://{hostname}{path}",
            ]
        )
    print(
        f"Renewed {certificate}; revision/expiry changed and strict external HTTPS checks passed."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    status_parser = sub.add_parser("status")
    status_parser.add_argument("--certificate", action="append", default=[])
    token_parser = sub.add_parser("install-token")
    token_parser.add_argument("--file")
    sub.add_parser("verify-authorization")
    renew_parser = sub.add_parser("renew")
    renew_parser.add_argument("--certificate", required=True, help="namespace/name")
    renew_parser.add_argument("--hostname", required=True)
    renew_parser.add_argument("--timeout", default="10m")
    args = parser.parse_args()
    if args.command == "status":
        return status(args.certificate)
    if args.command == "install-token":
        install_token(args.file)
    elif args.command == "verify-authorization":
        verify_auth()
    else:
        renew(args.certificate, args.hostname, args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
