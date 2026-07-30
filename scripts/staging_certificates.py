#!/usr/bin/env python3
"""Secret-safe, read-only cert-manager status and bounded single-certificate waits."""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "clusters/staging/certificates.json"
CONTEXT = "sugar-staging"
KINDS = ("certificates", "certificaterequests", "orders", "challenges")


def run_json(*args):
    result = subprocess.run(
        ["kubectl", "--context", CONTEXT, *args, "-o", "json"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def run_text(*args):
    return subprocess.run(
        ["kubectl", "--context", CONTEXT, *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout


def current_context():
    return subprocess.run(
        ["kubectl", "config", "current-context"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()


def clean(value):
    """Bound diagnostics and remove common credential/private material shapes."""
    text = str(value or "")
    text = re.sub(
        r"-----BEGIN [^-]+-----.*?(?:-----END [^-]+-----|$)", "[redacted]", text, flags=re.S
    )
    text = re.sub(r"(?i)\b(authorization|token|api[-_]?key)\s*[:=]\s*\S+", r"\1=[redacted]", text)
    text = re.sub(r"(?i)\bbearer\s+\S+", "Bearer [redacted]", text)
    text = re.sub(r"https?://\S+", "[url-redacted]", text)
    return " ".join(text.split())[:240] or "-"


def owner(item, kind):
    for ref in item.get("metadata", {}).get("ownerReferences", []):
        if ref.get("kind") == kind:
            return ref.get("name")
    return None


def condition(item, kind="Ready"):
    for cond in item.get("status", {}).get("conditions", []):
        if cond.get("type") == kind:
            return cond
    return {}


def collect():
    data = {}
    for kind in KINDS:
        data[kind] = run_json("get", kind, "-A").get("items", [])
    return data


def correlated(cert, data):
    ns = cert["namespace"]
    requests = [
        x
        for x in data["certificaterequests"]
        if x.get("metadata", {}).get("namespace") == ns and owner(x, "Certificate") == cert["name"]
    ]
    request_names = {x.get("metadata", {}).get("name") for x in requests}
    orders = [
        x
        for x in data["orders"]
        if x.get("metadata", {}).get("namespace") == ns
        and owner(x, "CertificateRequest") in request_names
    ]
    order_names = {x.get("metadata", {}).get("name") for x in orders}
    challenges = [
        x
        for x in data["challenges"]
        if x.get("metadata", {}).get("namespace") == ns and owner(x, "Order") in order_names
    ]

    def key(item):
        return item.get("metadata", {}).get("name", "")

    return sorted(requests, key=key), sorted(orders, key=key), sorted(challenges, key=key)


def render(inventory, data, secrets, issuer):
    lines = []
    issuer_ok = issuer.get("metadata", {}).get("name") == inventory["clusterIssuer"]
    solver = (((issuer.get("spec") or {}).get("acme") or {}).get("solvers") or [{}])[0]
    ref = ((solver.get("dns01") or {}).get("cloudflare") or {}).get("apiTokenSecretRef") or {}
    expected = inventory["cloudflareSecret"]
    secret = next(
        (
            x
            for x in secrets
            if x.get("metadata", {}).get("name") == expected["name"]
            and x.get("metadata", {}).get("namespace") == expected["namespace"]
        ),
        None,
    )
    secret_ok = bool(secret and expected["key"] in secret.get("data", {}))
    lines.append(
        f"issuer={inventory['clusterIssuer']} present={str(issuer_ok).lower()} secret={expected['namespace']}/{expected['name']} key={expected['key']} configured={str(ref.get('name') == expected['name'] and ref.get('key') == expected['key']).lower()} present={str(secret_ok).lower()}"  # noqa: E501
    )
    cert_items = {
        (x.get("metadata", {}).get("namespace"), x.get("metadata", {}).get("name")): x
        for x in data["certificates"]
    }
    tls_names = {
        (x.get("metadata", {}).get("namespace"), x.get("metadata", {}).get("name")) for x in secrets
    }
    for wanted in sorted(inventory["certificates"], key=lambda x: (x["namespace"], x["name"])):
        item = cert_items.get((wanted["namespace"], wanted["name"]), {})
        status = item.get("status", {})
        cond = condition(item)
        spec = item.get("spec", {})
        issuer_ref = spec.get("issuerRef", {})
        lines.append(
            f"certificate={wanted['namespace']}/{wanted['name']} dns={','.join(spec.get('dnsNames') or wanted['dnsNames'])} ready={cond.get('status', 'Missing')} reason={clean(cond.get('reason', '-'))} revision={status.get('revision', '-')} notBefore={status.get('notBefore', '-')} notAfter={status.get('notAfter', '-')} renewalTime={status.get('renewalTime', '-')} issuer={issuer_ref.get('kind', '-')}/{issuer_ref.get('name', '-')} secret={spec.get('secretName', wanted['name'])} secretPresent={str((wanted['namespace'], spec.get('secretName', wanted['name'])) in tls_names).lower()}"  # noqa: E501
        )
        requests, orders, challenges = correlated(wanted, data)
        active_order_names = {
            x.get("metadata", {}).get("name")
            for x in orders
            if x.get("status", {}).get("state") not in ("valid", "invalid")
        }
        for challenge in challenges:
            state = challenge.get("status", {}).get("state", "pending")
            active = owner(challenge, "Order") in active_order_names and state not in (
                "valid",
                "invalid",
            )
            lines.append(
                f"  challenge={challenge.get('metadata', {}).get('name', '[malformed]')} state={state} classification={'active' if active else 'stale'} reason={clean(challenge.get('status', {}).get('reason'))}"  # noqa: E501
            )
        lines.append(
            f"  resources=requests:{len(requests)} orders:{len(orders)} challenges:{len(challenges)}"  # noqa: E501
        )
    return "\n".join(lines)


def snapshot(inventory):
    data = collect()
    expected = inventory["cloudflareSecret"]
    secrets = []
    try:
        keys = run_text(
            "get",
            "secret",
            expected["name"],
            "-n",
            expected["namespace"],
            "-o",
            'go-template={{range $k, $_ := .data}}{{$k}}{{"\\n"}}{{end}}',
        )
        secrets.append(
            {
                "metadata": {"name": expected["name"], "namespace": expected["namespace"]},
                "data": {key: None for key in keys.splitlines()},
            }
        )
    except subprocess.CalledProcessError:
        pass
    # Existence is checked through metadata.name; private Secret data is never requested.
    for cert in inventory["certificates"]:
        try:
            name = run_text(
                "get",
                "secret",
                cert["name"],
                "-n",
                cert["namespace"],
                "-o",
                "jsonpath={.metadata.name}",
            )
            secrets.append({"metadata": {"name": name, "namespace": cert["namespace"]}})
        except subprocess.CalledProcessError:
            pass
    try:
        issuer = run_json("get", "clusterissuer", inventory["clusterIssuer"])
    except subprocess.CalledProcessError:
        issuer = {}
    return render(inventory, data, secrets, issuer)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("status", "wait"))
    parser.add_argument("--env", required=True)
    parser.add_argument("--certificate")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if args.env != "staging":
        parser.error("this command requires --env staging")
    if current_context() != CONTEXT:
        parser.error(f"current Kubernetes context must be {CONTEXT}")
    inventory = json.loads(INVENTORY.read_text())
    if args.command == "status":
        print(snapshot(inventory))
        return
    if (
        not args.certificate
        or "/" not in args.certificate
        or args.timeout < 1
        or args.timeout > 900
    ):
        parser.error("wait requires --certificate namespace/name and --timeout 1..900")
    wanted = [
        x for x in inventory["certificates"] if f"{x['namespace']}/{x['name']}" == args.certificate
    ]
    if len(wanted) != 1:
        parser.error("certificate is not in the staging inventory")
    inventory["certificates"] = wanted
    deadline = time.monotonic() + args.timeout
    while True:
        output = snapshot(inventory)
        print(output, flush=True)
        line = next(x for x in output.splitlines() if x.startswith("certificate="))
        if (
            " ready=True " in line
            and " secretPresent=true" in line
            and "classification=active" not in output
            and "Found no Zones" not in output
        ):
            return
        if time.monotonic() >= deadline:
            print("bounded wait expired without readiness", file=sys.stderr)
            raise SystemExit(3)
        time.sleep(min(15, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    main()
