#!/usr/bin/env python3
"""Render a deterministic, redacted cert-manager resource report."""

from __future__ import annotations

import json
import sys

REDACTED_WORDS = ("token", "secret", "authorization", "credential")


def safe(value: object) -> str:
    text = "" if value is None else str(value).replace("\n", " ")
    lowered = text.lower()
    if any(word in lowered for word in REDACTED_WORDS):
        return "[redacted]"
    return text


def condition(resource: dict, kind: str = "Ready") -> tuple[str, str, str]:
    for item in resource.get("status", {}).get("conditions", []):
        if item.get("type") == kind:
            return (
                str(item.get("status", "Unknown")),
                safe(item.get("reason")) or "-",
                safe(item.get("message")) or "-",
            )
    return "Unknown", "-", "-"


def owner_names(resource: dict) -> set[str]:
    return {str(x.get("name")) for x in resource.get("metadata", {}).get("ownerReferences", [])}


def main() -> int:
    document = json.load(sys.stdin)
    inventory = document["inventory"]
    resources = document["resources"]
    events = resources.get("events", {}).get("items", [])
    result = 0
    for wanted in inventory:
        namespace, cert_name, hostname = wanted.split("/", 2)
        certs = [
            x
            for x in resources["certificates"].get("items", [])
            if x.get("metadata", {}).get("namespace") == namespace
            and x.get("metadata", {}).get("name") == cert_name
        ]
        print(f"Certificate: {namespace}/{cert_name}")
        print(f"DNS name: {hostname}")
        if not certs:
            print("Ready: False (DoesNotExist)")
            print("Secret present: False")
            print("CertificateRequests: none\nOrders: none\nChallenges: none\nEvents: none")
            result = 1
            continue
        cert = certs[0]
        ready, reason, message = condition(cert)
        spec, status = cert.get("spec", {}), cert.get("status", {})
        issuer = spec.get("issuerRef", {})
        issuer_name = issuer.get("name")
        if not issuer_name:
            result = 1
        print(f"Ready: {ready} ({reason}) - {message}")
        print(f"Issuer: {issuer.get('kind', 'Issuer')}/{issuer_name or 'MISSING'}")
        issuer_resources = [
            item
            for item in resources["issuers"].get("items", [])
            if item.get("metadata", {}).get("name") == issuer_name
        ]
        if issuer_resources:
            issuer_ready, issuer_reason, _ = condition(issuer_resources[0])
            print(f"Issuer Ready: {issuer_ready} ({issuer_reason})")
        else:
            print("Issuer Ready: Unknown (DoesNotExist)")
            result = 1
        dns_names = spec.get("dnsNames", [])
        print(f"Certificate DNS names: {', '.join(map(str, dns_names)) or '-'}")
        if hostname not in dns_names:
            result = 1
        secret_present = bool(
            document.get("secrets", {}).get(namespace, {}).get(spec.get("secretName", ""))
        )
        print(f"Secret present: {secret_present}")
        print(f"Revision: {status.get('revision', '-')}")
        not_before = status.get("notBefore", "-")
        not_after = status.get("notAfter", "-")
        renewal = status.get("renewalTime", "-")
        print(f"Validity: notBefore={not_before} notAfter={not_after} renewalTime={renewal}")
        requests = [
            x
            for x in resources["requests"].get("items", [])
            if x.get("metadata", {}).get("namespace") == namespace and cert_name in owner_names(x)
        ]
        request_names = {x.get("metadata", {}).get("name") for x in requests}
        orders = [
            x
            for x in resources["orders"].get("items", [])
            if x.get("metadata", {}).get("namespace") == namespace
            and owner_names(x) & request_names
        ]
        order_names = {x.get("metadata", {}).get("name") for x in orders}
        challenges = [
            x
            for x in resources["challenges"].get("items", [])
            if x.get("metadata", {}).get("namespace") == namespace and owner_names(x) & order_names
        ]
        for label, items in (
            ("CertificateRequests", requests),
            ("Orders", orders),
            ("Challenges", challenges),
        ):
            print(f"{label}:")
            if not items:
                print("  none")
            for item in items:
                name = item.get("metadata", {}).get("name", "unknown")
                state = item.get("status", {}).get("state")
                cstatus, creason, cmessage = condition(item)
                active = state in {"pending", "processing"} or (
                    state is None and cstatus == "Unknown"
                )
                activity = "active" if active else "stale/complete"
                state_text = safe(state) or cstatus
                print(
                    f"  {name}: {activity} state={state_text} "
                    f"reason={creason} message={cmessage}"
                )
        relevant = [
            e
            for e in events
            if e.get("metadata", {}).get("namespace") == namespace
            and e.get("involvedObject", {}).get("name")
            in (
                {cert_name}
                | request_names
                | order_names
                | {x.get("metadata", {}).get("name") for x in challenges}
            )
        ]
        print("Events:")
        if not relevant:
            print("  none")
        for event in relevant[-10:]:
            print(f"  {safe(event.get('reason')) or '-'}: {safe(event.get('message')) or '-'}")
        print()
        if ready != "True":
            result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
