#!/usr/bin/env python3
"""Secret-safe, read-only cert-manager status for the staging inventory."""

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "clusters/staging/certificates.json"
KINDS = (
    "certificates.cert-manager.io",
    "certificaterequests.cert-manager.io",
    "orders.acme.cert-manager.io",
    "challenges.acme.cert-manager.io",
)


def clean(value):
    text = str(value or "-")
    text = re.sub(r"-----BEGIN [^-]+-----.*", "[redacted]", text, flags=re.S)
    text = re.sub(r"(?i)authorization\s*:\s*\S+(?:\s+\S+)?", "authorization=[redacted]", text)
    text = re.sub(r"(?i)(token|api[-_ ]?key)\s*[:=]\s*\S+", r"\1=[redacted]", text)
    text = re.sub(r"https?://\S+", "[url-redacted]", text)
    return " ".join(text.split())[:240]


def owner(item, kind):
    return next(
        (
            x.get("name")
            for x in item.get("metadata", {}).get("ownerReferences", [])
            if x.get("kind") == kind
        ),
        None,
    )


def condition(item, kind="Ready"):
    return next(
        (x for x in item.get("status", {}).get("conditions", []) if x.get("type") == kind), {}
    )


def run_json(args):
    result = subprocess.run(
        ["kubectl", "--context", "sugar-staging", *args, "-o", "json"],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def collect():
    data = {kind: run_json(["get", kind, "-A"]).get("items", []) for kind in KINDS}
    data["clusterissuers.cert-manager.io"] = run_json(
        ["get", "clusterissuers.cert-manager.io"]
    ).get("items", [])
    return data


def render(data, inventory):
    lines = []
    certs = data.get(KINDS[0], [])
    requests = data.get(KINDS[1], [])
    orders = data.get(KINDS[2], [])
    challenges = data.get(KINDS[3], [])
    for expected in sorted(inventory["certificates"], key=lambda x: (x["namespace"], x["name"])):
        ns, name = expected["namespace"], expected["name"]
        cert = next(
            (
                x
                for x in certs
                if x.get("metadata", {}).get("namespace") == ns
                and x.get("metadata", {}).get("name") == name
            ),
            {},
        )
        spec, status, ready = cert.get("spec", {}), cert.get("status", {}), condition(cert)
        lines.append(f"Certificate {ns}/{name}")
        lines.append(
            "  DNS names: " + ", ".join(sorted(spec.get("dnsNames", expected["dnsNames"])))
        )
        lines.append(f"  Ready: {clean(ready.get('status'))} reason={clean(ready.get('reason'))}")
        for field in ("revision", "notBefore", "notAfter", "renewalTime"):
            lines.append(f"  {field}: {clean(status.get(field))}")
        ref = spec.get("issuerRef", {})
        lines.append(
            f"  issuer: {clean(ref.get('kind', 'ClusterIssuer'))}/{clean(ref.get('name'))}"
        )
        secret_state = "present" if status.get("_secretPresent") else "MISSING"
        lines.append(f"  expected Secret: {clean(spec.get('secretName', name))} ({secret_state})")
        owned = [
            x
            for x in requests
            if x.get("metadata", {}).get("namespace") == ns and owner(x, "Certificate") == name
        ]
        owned.sort(
            key=lambda x: (
                x.get("metadata", {}).get("creationTimestamp", ""),
                x.get("metadata", {}).get("name", ""),
            )
        )
        active_request = owned[-1].get("metadata", {}).get("name") if owned else None
        owned_orders = [
            x
            for x in orders
            if x.get("metadata", {}).get("namespace") == ns
            and owner(x, "CertificateRequest") in {r.get("metadata", {}).get("name") for r in owned}
        ]
        order_to_request = {
            x.get("metadata", {}).get("name"): owner(x, "CertificateRequest") for x in owned_orders
        }
        related = [
            x
            for x in challenges
            if x.get("metadata", {}).get("namespace") == ns
            and owner(x, "Order") in order_to_request
        ]
        for ch in sorted(related, key=lambda x: x.get("metadata", {}).get("name", "")):
            state = ch.get("status", {}).get("state", "pending")
            freshness = (
                "active"
                if order_to_request.get(owner(ch, "Order")) == active_request
                and state not in ("valid", "expired")
                else "stale"
            )
            reason = ch.get("status", {}).get("reason") or condition(ch).get("message")
            lines.append(f"  Challenge {freshness} state={clean(state)} reason={clean(reason)}")
        lines.append("")
    secret = inventory["issuerSecret"]
    lines.append(
        f"Issuer Secret {secret['namespace']}/{secret['name']} key={secret['key']}: "
        + (
            "valid (issuer reference and key present)"
            if data.get("_issuerSecretValid")
            else "MISSING, WRONG KEY, OR ISSUER REFERENCE MISMATCH"
        )
    )
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=("status", "wait"))
    p.add_argument("--env", required=True)
    p.add_argument("--certificate")
    p.add_argument("--timeout", type=int, default=300)
    args = p.parse_args()
    inv = json.loads(INVENTORY.read_text())
    if args.env != "staging":
        p.error("only env=staging is permitted")
    if args.command == "wait" and (not args.certificate or args.timeout < 1 or args.timeout > 900):
        p.error("wait requires one certificate and timeout 1..900 seconds")
    context = subprocess.run(
        ["kubectl", "config", "current-context"], text=True, capture_output=True, check=True
    ).stdout.strip()
    if context != inv["context"]:
        p.error(f"current context must be {inv['context']}")
    data = collect()
    # Metadata-only presence checks avoid ever requesting a TLS Secret body.
    for cert in data[KINDS[0]]:
        ns, secret = cert.get("metadata", {}).get("namespace"), cert.get("spec", {}).get(
            "secretName"
        )
        cert.setdefault("status", {})["_secretPresent"] = (
            subprocess.run(
                [
                    "kubectl",
                    "--context",
                    inv["context"],
                    "get",
                    "secret",
                    secret,
                    "-n",
                    ns,
                    "-o",
                    "name",
                ],
                capture_output=True,
            ).returncode
            == 0
        )
    sec = inv["issuerSecret"]
    key_result = subprocess.run(
        [
            "kubectl",
            "--context",
            inv["context"],
            "get",
            "secret",
            sec["name"],
            "-n",
            sec["namespace"],
            "-o",
            f"go-template={{{{if index .data {json.dumps(sec['key'])}}}}}valid{{{{end}}}}",
        ],
        text=True,
        capture_output=True,
    )
    configured = set()
    for issuer in data["clusterissuers.cert-manager.io"]:
        for solver in issuer.get("spec", {}).get("acme", {}).get("solvers", []):
            ref = solver.get("dns01", {}).get("cloudflare", {}).get("apiTokenSecretRef", {})
            configured.add((ref.get("name"), ref.get("key")))
    data["_issuerSecretValid"] = (
        key_result.returncode == 0
        and key_result.stdout == "valid"
        and (sec["name"], sec["key"]) in configured
    )
    print(render(data, inv), end="")


if __name__ == "__main__":
    main()
