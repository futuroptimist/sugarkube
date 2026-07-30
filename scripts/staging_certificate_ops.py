#!/usr/bin/env python3
"""Deterministic, redacted, staging-only cert-manager operations."""

import argparse, base64, json, re, subprocess, sys, time
from pathlib import Path

INV = Path(__file__).with_name("staging_certificate_inventory.json")


def run(*argv, stdin=None):
    return subprocess.run(argv, input=stdin, text=True, check=True, capture_output=True).stdout


def sanitize(value):
    value = str(value or "-")
    value = re.sub(r"-----BEGIN[\s\S]*?-----END[^-]*-----", "[REDACTED]", value)
    value = re.sub(r"(?i)authorization\s*[:=]\s*\S+", "Authorization=[REDACTED]", value)
    value = re.sub(r"https?://\S+", "[REDACTED URL]", value)
    value = re.sub(r"(?i)\b(private|bearer)\b", "[REDACTED]", value)
    value = re.sub(r"(?i)(token|secret|api[-_ ]?key)\s*[:=]\s*\S+", r"\1=[REDACTED]", value)
    value = " ".join(value.split())
    return value[:180] + ("…" if len(value) > 180 else "")


def resources(kind, ns):
    out = run("kubectl", "--context", "sugar-staging", "-n", ns, "get", kind, "-o", "json")
    return json.loads(out).get("items", [])


def owner(resource, kind):
    refs = resource.get("metadata", {}).get("ownerReferences", [])
    return next(
        (x.get("uid") for x in refs if x.get("kind") == kind and x.get("controller", True)), None
    )


def condition(resource, kind="Ready"):
    return next(
        (x for x in resource.get("status", {}).get("conditions", []) if x.get("type") == kind), {}
    )


def secret_keys(ns, name):
    # Only metadata and key names are emitted; values are never decoded or displayed.
    fmt = "{.metadata.name}{'|'}{range $k,$v := .data}{$k}{' '}{end}"
    try:
        return run(
            "kubectl",
            "--context",
            "sugar-staging",
            "-n",
            ns,
            "get",
            "secret",
            name,
            "-o",
            "jsonpath=" + fmt,
        ).strip()
    except subprocess.CalledProcessError:
        return ""


def state(ns):
    data = {
        k: resources(k, ns) for k in ("certificates", "certificaterequests", "orders", "challenges")
    }
    data["clusterissuers"] = resources("clusterissuers", ns)
    return data


def render(entry, data, issuer_secret):
    cert = next(
        (x for x in data["certificates"] if x.get("metadata", {}).get("name") == entry["name"]),
        None,
    )
    if not cert:
        return f"Certificate {entry['namespace']}/{entry['name']} MALFORMED_OR_MISSING"
    m, spec, status = cert.get("metadata", {}), cert.get("spec", {}), cert.get("status", {})
    ready, issuer = condition(cert), spec.get("issuerRef") or {}
    lines = [
        f"Certificate {entry['namespace']}/{entry['name']}",
        f"  dnsNames: {','.join(sorted(spec.get('dnsNames') or [])) or '-'}",
        f"  Ready: {ready.get('status','Unknown')} reason={sanitize(ready.get('reason'))}",
        f"  revision: {status.get('revision','-')} notBefore={status.get('notBefore','-')} notAfter={status.get('notAfter','-')} renewalTime={status.get('renewalTime','-')}",
        f"  issuerRef: {issuer.get('kind','Issuer')}/{issuer.get('name','-')} expectedSecret: {spec.get('secretName','-')}",
    ]
    reqs = sorted(
        (x for x in data["certificaterequests"] if owner(x, "Certificate") == m.get("uid")),
        key=lambda x: (
            x.get("metadata", {}).get("creationTimestamp", ""),
            x.get("metadata", {}).get("name", ""),
        ),
    )
    req_uids = {x.get("metadata", {}).get("uid") for x in reqs}
    active_req = {x.get("metadata", {}).get("uid") for x in reqs[-1:]}
    orders = [x for x in data["orders"] if owner(x, "CertificateRequest") in req_uids]
    order_uids = {x.get("metadata", {}).get("uid") for x in orders}
    active_orders = {
        x.get("metadata", {}).get("uid")
        for x in orders
        if owner(x, "CertificateRequest") in active_req
    }
    for request in reqs:
        rc = condition(request)
        lines.append(
            f"  CertificateRequest {request.get('metadata',{}).get('name','?')}: Ready={rc.get('status','Unknown')} reason={sanitize(rc.get('reason'))}"
        )
    for order in sorted(orders, key=lambda x: x.get("metadata", {}).get("name", "")):
        os = order.get("status", {})
        lines.append(
            f"  Order {order.get('metadata',{}).get('name','?')}: state={os.get('state','pending')} reason={sanitize(os.get('reason'))}"
        )
    challenges = [x for x in data["challenges"] if owner(x, "Order") in order_uids]
    for ch in sorted(challenges, key=lambda x: x.get("metadata", {}).get("name", "")):
        cs = ch.get("status", {})
        active = owner(ch, "Order") in active_orders and (
            cs.get("processing") is True
            or ("processing" not in cs and cs.get("state") in (None, "", "pending"))
        )
        lines.append(
            f"  Challenge {ch.get('metadata',{}).get('name','?')}: {'ACTIVE' if active else 'STALE'} state={cs.get('state','pending')} reason={sanitize(cs.get('reason'))}"
        )
    secret = spec.get("secretName", "")
    lines.append(
        f"  TLS Secret: {'present' if secret and secret_keys(entry['namespace'],secret) else 'MISSING'}"
    )
    shape = secret_keys(issuer_secret["namespace"], issuer_secret["name"])
    keys = shape.partition("|")[2].split()
    issuer_resource = next(
        (
            x
            for x in data.get("clusterissuers", [])
            if x.get("metadata", {}).get("name") == issuer.get("name")
        ),
        None,
    )
    refs = []
    if issuer_resource:
        for solver in issuer_resource.get("spec", {}).get("acme", {}).get("solvers", []):
            ref = solver.get("dns01", {}).get("cloudflare", {}).get("apiTokenSecretRef")
            if ref:
                refs.append((ref.get("name"), ref.get("key")))
    configured = (issuer_secret["name"], issuer_secret["key"]) in refs
    valid = configured and issuer_secret["key"] in keys
    lines.append(
        f"  issuer Secret contract: {'valid' if valid else 'MISSING name/key'} ({issuer_secret['namespace']}/{issuer_secret['name']} key={issuer_secret['key']})"
    )
    if not issuer_resource:
        lines.append("  issuer validation: MISSING issuer")
    return "\n".join(lines)


def converged(cert, data, secret_present):
    if condition(cert).get("status") != "True" or not secret_present:
        return False
    reqs = sorted(
        (
            x
            for x in data["certificaterequests"]
            if owner(x, "Certificate") == cert.get("metadata", {}).get("uid")
        ),
        key=lambda x: x.get("metadata", {}).get("creationTimestamp", ""),
    )
    if not reqs:
        return True  # cert-manager may already have garbage-collected successful ACME resources.
    request = reqs[-1]
    orders = [
        x
        for x in data["orders"]
        if owner(x, "CertificateRequest") == request.get("metadata", {}).get("uid")
    ]
    if any(x.get("status", {}).get("state") not in ("valid",) for x in orders):
        return False
    order_uids = {x.get("metadata", {}).get("uid") for x in orders}
    challenges = [x for x in data["challenges"] if owner(x, "Order") in order_uids]
    for challenge in challenges:
        status = challenge.get("status", {})
        if (
            status.get("state") not in ("valid",)
            or "found no zones" in str(status.get("reason", "")).lower()
        ):
            return False
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=("status", "wait", "renew", "verify"))
    p.add_argument("--env", required=True)
    p.add_argument("--namespace", required=True)
    p.add_argument("--certificate", required=True)
    p.add_argument("--timeout", type=int, default=300)
    a = p.parse_args()
    inv = json.loads(INV.read_text())
    if a.env != "staging":
        p.error("only env=staging is permitted")
    if run("kubectl", "config", "current-context").strip() != inv["context"]:
        p.error("current context must be exactly sugar-staging")
    matches = [
        x
        for x in inv["certificates"]
        if x["namespace"] == a.namespace and x["name"] == a.certificate
    ]
    if len(matches) != 1:
        p.error("target exactly one certificate from the staging inventory")
    if not 1 <= a.timeout <= 900:
        p.error("timeout must be between 1 and 900 seconds")
    entry = matches[0]
    if a.command == "status":
        print(render(entry, state(a.namespace), inv["issuerSecret"]))
        return
    if a.command == "verify":
        encoded = run(
            "kubectl",
            "--context",
            inv["context"],
            "-n",
            a.namespace,
            "get",
            "secret",
            a.certificate,
            "-o",
            "jsonpath={.data.tls\\.crt}",
        )
        pem = base64.b64decode(encoded, validate=True).decode()
        print(
            run(
                "openssl",
                "x509",
                "-noout",
                "-subject",
                "-issuer",
                "-serial",
                "-dates",
                "-ext",
                "subjectAltName",
                stdin=pem,
            ),
            end="",
        )
        return
    deadline = time.monotonic() + a.timeout
    while True:
        current = state(a.namespace)
        print(render(entry, current, inv["issuerSecret"]), flush=True)
        cert = next(
            (
                x
                for x in current["certificates"]
                if x.get("metadata", {}).get("name") == a.certificate
            ),
            {},
        )
        if converged(cert, current, secret_keys(a.namespace, a.certificate)):
            return
        if time.monotonic() >= deadline:
            if a.command == "renew":
                run(
                    "cmctl",
                    "renew",
                    "--context",
                    inv["context"],
                    "--namespace",
                    a.namespace,
                    a.certificate,
                )
                print(
                    f"Existing Challenges did not converge; targeted renewal requested for {a.namespace}/{a.certificate}"
                )
                return
            raise SystemExit("bounded wait expired; stop before considering one targeted renewal")
        time.sleep(min(15, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    main()
