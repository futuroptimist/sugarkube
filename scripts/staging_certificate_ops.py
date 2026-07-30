#!/usr/bin/env python3
"""Bounded, redacted and staging-only cert-manager operations."""

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = ROOT / "clusters/staging/certificates.json"
REDACTIONS = (
    (re.compile(r"(?i)authorization\s*[:=]\s*(?:bearer\s+)?\S+"), "authorization=[REDACTED]"),
    (re.compile(r"(?i)(token|api[_-]?key|secret)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"https?://\S+"), "[URL REDACTED]"),
    (re.compile(r"-----BEGIN [^-]*(?:PRIVATE )?KEY-----.*", re.S), "[KEY MATERIAL REDACTED]"),
)


def sanitize(value, limit=240):
    text = " ".join(str(value or "-").split())
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)
    return text[:limit] + ("…" if len(text) > limit else "")


def run_json(context, args):
    proc = subprocess.run(
        ["kubectl", "--context", context, *args, "-o", "json"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError(sanitize(proc.stderr))
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("kubectl returned malformed JSON") from exc


def condition(resource, kind="Ready"):
    for item in resource.get("status", {}).get("conditions", []):
        if item.get("type") == kind:
            return item.get("status", "Unknown"), sanitize(item.get("reason", "-"))
    return "Unknown", "-"


def owner_uid(resource, kind):
    for owner in resource.get("metadata", {}).get("ownerReferences", []):
        if owner.get("kind") == kind:
            return owner.get("uid")
    return None


def items_by_owner(items, kind, uid):
    return [item for item in items if owner_uid(item, kind) == uid]


def collect(inventory):
    context = inventory["context"]
    certs = run_json(context, ["get", "certificates", "--all-namespaces"]).get("items", [])
    requests = run_json(context, ["get", "certificaterequests", "--all-namespaces"]).get(
        "items", []
    )
    orders = run_json(context, ["get", "orders.acme.cert-manager.io", "--all-namespaces"]).get(
        "items", []
    )
    challenges = run_json(
        context, ["get", "challenges.acme.cert-manager.io", "--all-namespaces"]
    ).get("items", [])
    # Metadata only: never retrieve Secret data or YAML.
    secret_names = set()
    for entry in inventory["certificates"]:
        expected_secret = entry.get("secretName", entry["name"])
        proc = subprocess.run(
            [
                "kubectl",
                "--context",
                context,
                "get",
                "secret",
                "-n",
                entry["namespace"],
                expected_secret,
                "-o",
                "name",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0:
            secret_names.add((entry["namespace"], expected_secret))
    issuer_cfg = inventory["issuerSecret"]
    issuer = run_json(context, ["get", "clusterissuers.cert-manager.io"])
    key_proc = subprocess.run(
        [
            "kubectl",
            "--context",
            context,
            "get",
            "secret",
            "-n",
            issuer_cfg["namespace"],
            issuer_cfg["name"],
            "-o",
            'go-template={{range $k, $_ := .data}}{{$k}}{{"\\n"}}{{end}}',
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    keys = sorted(key_proc.stdout.splitlines()) if key_proc.returncode == 0 else []
    expected = {(x["namespace"], x["name"]): x for x in inventory["certificates"]}
    actual = {
        (x.get("metadata", {}).get("namespace"), x.get("metadata", {}).get("name")): x
        for x in certs
    }
    issuer_secret_state = "yes" if issuer_cfg["key"] in keys else "no"
    lines = [
        f"context: {context}",
        f"issuer-secret: {issuer_cfg['namespace']}/{issuer_cfg['name']} "
        f"key={issuer_cfg['key']} present={issuer_secret_state}",
    ]
    issuer_names = {x.get("metadata", {}).get("name") for x in issuer.get("items", [])}
    ok = issuer_cfg["key"] in keys
    for key in sorted(expected):
        wanted, cert = expected[key], actual.get(key)
        lines.append(f"certificate: {key[0]}/{key[1]}")
        if not cert:
            lines.append("  malformed: certificate missing")
            ok = False
            continue
        spec, status = cert.get("spec", {}), cert.get("status", {})
        ready, reason = condition(cert)
        issuer_ref = spec.get("issuerRef", {})
        issuer_name = issuer_ref.get("name", "-")
        secret_name = spec.get("secretName", "-")
        dns = sorted(spec.get("dnsNames", []))
        issuer_state = "yes" if issuer_name in issuer_names else "no"
        secret_state = "yes" if (key[0], secret_name) in secret_names else "no"
        lines.extend(
            [
                f"  dnsNames: {','.join(dns) or '-'}",
                f"  ready: {ready} reason={reason}",
                f"  revision: {status.get('revision', '-')}",
                f"  notBefore: {status.get('notBefore', '-')}",
                f"  notAfter: {status.get('notAfter', '-')}",
                f"  renewalTime: {status.get('renewalTime', '-')}",
                f"  issuer: {issuer_ref.get('kind', 'Issuer')}/{issuer_name} "
                f"present={issuer_state}",
                f"  secret: {key[0]}/{secret_name} present={secret_state}",
            ]
        )
        cert_uid = cert.get("metadata", {}).get("uid")
        owned_requests = items_by_owner(requests, "Certificate", cert_uid)
        active_request = max(
            owned_requests,
            key=lambda x: (
                x.get("metadata", {}).get("creationTimestamp", ""),
                x.get("metadata", {}).get("name", ""),
            ),
            default=None,
        )
        active_order_uids = set()
        if active_request:
            active_order_uids = {
                x.get("metadata", {}).get("uid")
                for x in items_by_owner(
                    orders, "CertificateRequest", active_request.get("metadata", {}).get("uid")
                )
            }
        request_uids = {x.get("metadata", {}).get("uid") for x in owned_requests}
        cert_orders = [x for x in orders if owner_uid(x, "CertificateRequest") in request_uids]
        owned_challenges = [
            x
            for x in challenges
            if owner_uid(x, "Order") in {o.get("metadata", {}).get("uid") for o in cert_orders}
        ]
        for challenge in sorted(
            owned_challenges, key=lambda x: x.get("metadata", {}).get("name", "")
        ):
            active = owner_uid(challenge, "Order") in active_order_uids
            state = challenge.get("status", {}).get("state", "pending")
            reason_text = sanitize(challenge.get("status", {}).get("reason", "-"))
            classification = "active" if active else "stale"
            challenge_name = challenge.get("metadata", {}).get("name", "-")
            lines.append(
                f"  challenge: {challenge_name} classification={classification} "
                f"state={state} reason={reason_text}"
            )
        ok = (
            ok
            and ready == "True"
            and (key[0], secret_name) in secret_names
            and issuer_name in issuer_names
            and dns == sorted(wanted["dnsNames"])
        )
    return "\n".join(lines) + "\n", ok


def load_and_guard(args):
    if args.env != "staging":
        raise SystemExit("ERROR: env must be staging")
    inventory = json.loads(Path(args.inventory).read_text())
    current = subprocess.run(
        ["kubectl", "config", "current-context"], text=True, capture_output=True, check=False
    )
    if current.returncode or current.stdout.strip() != inventory["context"]:
        raise SystemExit(f"ERROR: current Kubernetes context must be {inventory['context']}")
    return inventory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("status", "wait", "renew"))
    parser.add_argument("--env", required=True)
    parser.add_argument("--inventory", default=str(DEFAULT_INVENTORY))
    parser.add_argument("--namespace")
    parser.add_argument("--certificate")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    inventory = load_and_guard(args)
    if args.command == "status":
        print(collect(inventory)[0], end="")
        return
    matches = [
        x
        for x in inventory["certificates"]
        if x["namespace"] == args.namespace and x["name"] == args.certificate
    ]
    if len(matches) != 1:
        raise SystemExit("ERROR: select exactly one inventoried --namespace and --certificate")
    deadline = time.monotonic() + max(1, min(args.timeout, 900))
    inventory = {**inventory, "certificates": matches}
    # Observe existing resources before renewal; renewal is never automatic.
    output, healthy = collect(inventory)
    print(output, end="")
    if args.command == "renew":
        while not healthy and time.monotonic() < deadline:
            time.sleep(min(15, max(0, deadline - time.monotonic())))
            output, healthy = collect(inventory)
            print(output, end="")
        if healthy:
            return
        subprocess.run(
            [
                "cmctl",
                "renew",
                "--context",
                inventory["context"],
                "-n",
                args.namespace,
                args.certificate,
            ],
            check=True,
        )
    while time.monotonic() < deadline:
        output, healthy = collect(inventory)
        print(output, end="")
        if healthy:
            return
        time.sleep(min(15, max(0, deadline - time.monotonic())))
    raise SystemExit("ERROR: bounded certificate wait expired")


if __name__ == "__main__":
    main()
