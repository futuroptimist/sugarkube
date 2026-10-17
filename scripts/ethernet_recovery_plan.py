#!/usr/bin/env python3
"""Plan Ethernet DHCP recovery from fresh, operator-collected evidence; never apply it.

mDNS is a locator, not an authority for etcd membership or Kubernetes identity.
Only --resolve-mdns performs bounded read-only Avahi queries. No service, filesystem
mutation, or cluster write is performed.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


class UnsafeEvidence(ValueError):
    """Incomplete or contradictory evidence requires operator investigation."""


def require(condition, message):
    if not condition:
        raise UnsafeEvidence(message)


def ipv4(value):
    address = ipaddress.IPv4Address(value)
    require(
        not (
            address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_unspecified
        ),
        "unusable Ethernet address",
    )
    return str(address)


def unique(items, key):
    result = {}
    for item in items:
        value = item[key]
        require(isinstance(value, str) and value, f"{key} must be a nonempty string")
        require(value not in result, f"duplicate {key}")
        result[value] = item
    return result


def plan(evidence, now=None):
    """Return review candidates, not executable commands or authorization.

    Health evidence must be from authenticated etcd endpoint health (a committed
    proposal), matched to endpoint status member/cluster IDs. TCP/API readiness
    and mDNS reachability are not equivalent. Offline evidence can never prove
    that these facts are still true when an operator acts.
    """
    now = now or datetime.now(timezone.utc)
    require(evidence["schema_version"] == 1, "unsupported evidence schema")
    captured = datetime.fromisoformat(evidence["captured_at"].replace("Z", "+00:00"))
    require(captured.tzinfo is not None, "capture time must include timezone")
    require(0 <= (now - captured).total_seconds() <= 300, "evidence must be <=300 seconds old")
    cluster = evidence["cluster_id"]
    require(isinstance(cluster, str) and cluster, "cluster ID must be a nonempty string")
    members = unique(evidence["members"], "id")
    require(len(members) == 3, "only established three-member embedded-etcd clusters supported")
    unique(members.values(), "name")
    for member in members.values():
        require(member["isLearner"] is False, "learner membership requires operator review")
        require(len(member["peerURLs"]) == 1, "expected one peer URL per member")
        url = urlsplit(member["peerURLs"][0])
        require(
            url.scheme == "https"
            and url.port == 2380
            and "@" not in url.netloc
            and not url.path
            and not url.query
            and not url.fragment,
            "unsupported peer URL",
        )
        ipv4(url.hostname)
    health = unique(evidence["health"], "member_id")
    require(set(health) <= set(members), "health contains unknown member")
    for entry in health.values():
        require(entry["cluster_id"] == cluster, "health cluster ID mismatch")
        require(type(entry["healthy"]) is bool, "health must be boolean")
        require(entry["method"] == "authenticated-etcd-proposal", "unproven health method")
    healthy = {key for key, value in health.items() if value["healthy"]}
    result = {
        "mode": "operator-intervention",
        "observed_healthy_voters": len(healthy),
        "required_voters": 2,
        "automatic_actions": [],
        "candidates": [],
        "constraints": [
            "Offline evidence is advisory; recheck identity and quorum "
            "immediately before each action.",
            "Never reset membership, remove members, delete/move databases "
            "or restart peers in bulk.",
        ],
    }
    if len(healthy) < 2:
        result["constraints"].append(
            "Live quorum is not proven (this does not prove permanent quorum loss). "
            "Stop automation. Preserve all DBs and cold verified backups. "
            "Total quorum loss requires explicit operator choice of an authoritative seed, "
            "followed by controlled recovery and sequential peer rejoin."
        )
        return result

    nodes = unique(evidence["nodes"], "name")
    require(len(nodes) == 3, "need evidence for all three nodes")
    unique(nodes.values(), "member_id")
    require({node["member_id"] for node in nodes.values()} == set(members), "membership mismatch")
    addresses = set()
    candidates = []
    for name, node in nodes.items():
        member = members[node["member_id"]]
        metadata = node["object"]["metadata"]
        require(metadata["name"] == name, "Node name mismatch")
        require(metadata["uid"] and metadata["resourceVersion"], "Node identity missing")
        annotations = metadata["annotations"]
        require(
            annotations["etcd.k3s.cattle.io/node-name"] == member["name"],
            "etcd member name does not match Node annotation",
        )
        require(node["mdns_name"] == name + ".local", "unexpected mDNS identity")
        require(node["interface"] and not node["interface"].startswith("wl"), "Ethernet only")
        current = ipv4(node["ethernet_ipv4"])
        require(node["mdns_ipv4"] == [current], "ambiguous mDNS or Ethernet mismatch")
        require(current not in addresses, "duplicate Ethernet address")
        addresses.add(current)
        expected_peer = f"https://{current}:2380"
        changes = {}
        if member["peerURLs"] != [expected_peer]:
            # A healthy voter must not be disrupted if that would consume quorum.
            require(
                len(healthy - {node["member_id"]}) >= 2,
                "cannot isolate changed member while preserving two healthy voters",
            )
            changes["membership_review"] = {
                "member_id": node["member_id"],
                "old_peer_urls": member["peerURLs"],
                "candidate_peer_urls": [expected_peer],
            }
        status_addresses = node["object"]["status"]["addresses"]
        internal = [a for a in status_addresses if a["type"] == "InternalIP"]
        require(len(internal) == 1, "missing or dual-stack Node InternalIP requires review")
        ipv4(internal[0]["address"])
        if internal[0]["address"] != current:
            require(
                annotations.get("k3s.io/internal-ip") == current,
                "Node annotation does not corroborate current Ethernet IP",
            )
            replacement = [
                {**a, "address": current} if a["type"] == "InternalIP" else dict(a)
                for a in status_addresses
            ]
            changes["status_patch_review"] = {
                "subresource": "status",
                "type": "json",
                "patch": [
                    {"op": "test", "path": "/metadata/uid", "value": metadata["uid"]},
                    {
                        "op": "test",
                        "path": "/metadata/resourceVersion",
                        "value": metadata["resourceVersion"],
                    },
                    {"op": "test", "path": "/status/addresses", "value": status_addresses},
                    {"op": "replace", "path": "/status/addresses", "value": replacement},
                ],
            }
        # Effective join targets must be inspected in systemd CLI, env and YAML.
        # A hostname in YAML cannot override an old --server argument.
        targets = node["join_targets"]
        require(isinstance(targets, list), "join_targets must include every effective source")
        stale_targets = []
        for target in targets:
            url = urlsplit(target)
            require(
                url.scheme == "https"
                and url.port == 6443
                and "@" not in url.netloc
                and not url.query
                and not url.fragment
                and not url.path,
                "unsupported join target",
            )
            if url.hostname not in {n + ".local" for n in nodes}:
                stale_targets.append(target)
        if stale_targets:
            changes["join_target_review"] = stale_targets
        if changes:
            candidates.append({"node": name, **changes})
    result["mode"] = "live-quorum-review" if candidates else "no-change"
    result["candidates"] = candidates
    result["constraints"].append(
        "Review one member at a time; verify peer TLS, supported YAML and all CLI/env overrides. "
        "A status-only patch is a last resort after proving local identity; it does not fix etcd. "
        "Recollect evidence after every action; this plan is not an execution queue."
    )
    return result


def resolve_mdns(evidence):
    """Refresh locators only; leave the age of the quorum evidence unchanged."""
    nodes = evidence["nodes"]
    require(len(nodes) == 3, "expected three nodes for bounded discovery")
    for node in nodes:
        name = node["mdns_name"]
        require(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.local", name),
            "invalid mDNS hostname",
        )
        response = subprocess.run(
            ["avahi-resolve-host-name", "-4", name],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        fields = response.stdout.split()
        require(len(fields) == 2 and fields[0] == name, "ambiguous mDNS response")
        node["mdns_ipv4"] = [ipv4(fields[1])]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "evidence", type=Path, help="fresh operator-collected JSON; see recovery guide"
    )
    parser.add_argument(
        "--resolve-mdns", action="store_true", help="refresh IPv4 locators via Avahi"
    )
    args = parser.parse_args()
    try:
        evidence = json.loads(args.evidence.read_text())
        if args.resolve_mdns:
            resolve_mdns(evidence)
        result = plan(evidence)
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        IndexError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        # Do not echo input values, which could include credentials in malformed URLs.
        result = {
            "mode": "operator-intervention",
            "automatic_actions": [],
            "candidates": [],
            "error": (
                str(error)
                if isinstance(error, UnsafeEvidence)
                else f"Invalid evidence ({type(error).__name__}); review input locally."
            ),
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result["mode"] == "operator-intervention" else 0


if __name__ == "__main__":
    raise SystemExit(main())
