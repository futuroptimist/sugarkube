#!/usr/bin/env python3
"""Offline admission of captured evidence; no host discovery or migration executor."""

import argparse
import copy
import hashlib
import ipaddress
import json
import re
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

CATALOG = Path(__file__).with_name("migration") / "resolver-v1-to-directory-v1.json"
CATALOG_SHA256 = "d3ba2e70b88cc82e356a0e879d9c8a50fcb30fa69e327efe25aa45dc804f27a9"
CONFIG = "/etc/rancher/k3s/sugarkube-dns.json"
KUBECONFIG_DIGEST_KIND = "k3s-kubeconfig-inventory-v1"
VIEW = {"kind": "resolved-stub-directory-v1", "symlink": "../run/systemd/resolve/stub-resolv.conf"}
ENROLLMENT_KEYS = set(
    (
        "schema_version k3s_version interface local_ipv4 cluster_id local_member_id "
        "verified_backup files members completion_https_urls pod_resolv_source armed "
        "dual_enrolled local_database machine_id_sha256 systemd_sha256 yaml_fragments "
        "etcd_tls kubeconfig"
    ).split()
)


class Refused(ValueError):
    """A fixed diagnostic, never untrusted input text."""


def require(condition, message):
    if not condition:
        raise Refused(message)


def shape(value, keys, message):
    require(type(value) is dict and set(value) == set(keys), message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def fingerprint(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value), "invalid digest")


def identifier(value):
    require(
        type(value) is str and re.fullmatch(r"[1-9][0-9]{0,19}", value) and int(value) < 2**64,
        "invalid identity",
    )


def path_name(value):
    require(
        type(value) is str
        and value.startswith("/")
        and str(PurePosixPath(value)) == value
        and ".." not in value.split("/")
        and not value.startswith("//"),
        "ambiguous path",
    )


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def parse(raw):
    try:
        return json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(Refused("nonfinite JSON number")),
        )
    except (ValueError, TypeError, RecursionError) as exc:
        raise Refused("invalid or ambiguous JSON") from exc


def kubeconfig_inventory_digest(config):
    """Hash a supplied parsed kubeconfig using historical inventory semantics.

    This pure capture-preparation helper never reads YAML, credentials or host paths.
    Its caller supplies a mapping parsed offline; no contents are returned or logged.
    The original mapping is unchanged. This is not a certificate/TLS validation.
    """
    try:
        config = copy.deepcopy(config)
        require(
            len(config["clusters"]) == len(config["contexts"]) == 1,
            "one explicit API trust context required",
        )
        cluster = config["clusters"][0]
        context = config["contexts"][0]
        require(
            set(cluster["cluster"]) == {"server", "certificate-authority-data"}
            and cluster["cluster"]["certificate-authority-data"]
            and config["current-context"] == context["name"]
            and context["context"]["cluster"] == cluster["name"],
            "unsupported kubeconfig trust context",
        )
        require(
            len(config["users"]) == 1 and context["context"]["user"] == config["users"][0]["name"],
            "unsupported kubeconfig user context",
        )
        user = config["users"][0]["user"]
        require(
            set(user) == {"client-certificate-data", "client-key-data"}
            and all(isinstance(value, str) and value for value in user.values()),
            "unsupported kubeconfig credential layout",
        )
        config["users"][0]["user"] = {key: "rotating-client-credential" for key in user}
        # Preserve the historical default separators and absence of a trailing newline.
        return sha(json.dumps(config, sort_keys=True, allow_nan=False).encode())
    except Refused:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError) as exc:
        raise Refused("malformed supplied kubeconfig mapping") from exc


def artifacts(catalog, enrollment, label, view):
    """Render only pinned literals and the historical sorted JSON config format."""
    entry = catalog["artifacts"][label]
    result = dict(entry["runtime_sha256"])
    result.update({p: sha(text.encode()) for p, text in entry["templates"].items()})
    config = {
        "schema_version": 2,
        "interface": enrollment["interface"],
        "pod_resolv_source": enrollment["pod_resolv_source"],
        "members": [{"hostname": m["hostname"]} for m in enrollment["members"]],
    }
    if label == "target":
        config["resolver_view"] = view
    result[CONFIG] = sha((json.dumps(config, sort_keys=True) + "\n").encode())
    return result


def metadata(record, expected, kind="file", uid=0, gid=0, digest_kind="raw-sha256"):
    shape(
        record,
        {"kind", "uid", "gid", "mode", "sha256", "digest_kind"},
        "missing or ambiguous file metadata",
    )
    require(
        record["digest_kind"] == ("none" if expected is None else digest_kind),
        "wrong fingerprint semantics",
    )
    require(
        record["kind"] == kind
        and type(record["uid"]) is int
        and record["uid"] == uid
        and type(record["gid"]) is int
        and record["gid"] == gid,
        "untrusted file type or ownership",
    )
    require(
        type(record["mode"]) is int
        and 0 <= record["mode"] <= 0o777
        and (kind == "socket" or not record["mode"] & 0o022),
        "unsafe file mode",
    )
    require(record["sha256"] == expected, "modified or missing captured file")


def enrollment_check(e):
    shape(e, ENROLLMENT_KEYS, "unsupported enrollment schema or resolver descriptor")
    require(
        type(e["schema_version"]) is int
        and e["schema_version"] == 2
        and e["armed"] is True
        and e["dual_enrolled"] is True,
        "numeric-only/v1 or incomplete enrollment needs a separate consensus transition",
    )
    require(e["k3s_version"] in ("v1.34.5+k3s1", "v1.35.4+k3s1"), "unsupported K3s version")
    require(
        type(e["interface"]) is str
        and re.fullmatch(r"[a-zA-Z0-9_.:-]{1,15}", e["interface"])
        and not e["interface"].startswith("wl"),
        "unsupported interface",
    )
    require(
        e["pod_resolv_source"] == "/run/systemd/resolve/resolv.conf",
        "unsupported pod resolver source",
    )
    require(e["verified_backup"] is True, "verified backup required")
    identifier(e["cluster_id"])
    identifier(e["local_member_id"])
    require(
        type(e["members"]) is list and len(e["members"]) == 3, "three original members required"
    )
    for member in e["members"]:
        shape(member, {"id", "name", "hostname", "node_uid"}, "unsupported member schema")
        identifier(member["id"])
        for key in ("name", "node_uid"):
            require(
                type(member[key]) is str and re.fullmatch(r"[a-zA-Z0-9-]{1,128}", member[key]),
                "invalid member or Node identity",
            )
        require(
            type(member["hostname"]) is str
            and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}\.local", member["hostname"]),
            "invalid hostname",
        )
    for key in ("id", "name", "hostname", "node_uid"):
        require(len({m[key] for m in e["members"]}) == 3, "duplicate identity")
    require(e["local_member_id"] in {m["id"] for m in e["members"]}, "local member mismatch")
    require(
        e["local_database"] == {"cluster_id": e["cluster_id"], "member_id": e["local_member_id"]},
        "database identity mismatch",
    )
    for key in ("machine_id_sha256", "systemd_sha256"):
        fingerprint(e[key])
    require(type(e["files"]) is dict and e["files"], "missing configuration fingerprints")
    for path, digest in e["files"].items():
        path_name(path)
        if digest is not None:
            fingerprint(digest)
    shape(e["etcd_tls"], {"ca", "cert", "key"}, "unsupported trust schema")
    for path in [e["kubeconfig"], *e["etcd_tls"].values()]:
        path_name(path)
    for path in [
        e["kubeconfig"],
        e["etcd_tls"]["ca"],
        "/var/lib/rancher/k3s/server/tls/etcd/peer-ca.crt",
        "/etc/rancher/k3s/sugarkube-network-prestart.sh",
        "/etc/systemd/system/k3s.service.d/20-sugarkube-network.conf",
    ]:
        require(e["files"].get(path) is not None, "missing trust or network fingerprint")
    require(
        type(e["yaml_fragments"]) is list
        and len(set(e["yaml_fragments"])) == len(e["yaml_fragments"]),
        "ambiguous YAML inventory",
    )
    require(
        all(p in e["files"] and e["files"][p] is not None for p in e["yaml_fragments"]),
        "missing YAML fingerprint",
    )
    require(
        type(e["completion_https_urls"]) is list and 1 <= len(e["completion_https_urls"]) <= 8,
        "missing workload prerequisites",
    )

    for value in e["completion_https_urls"]:
        url = urlsplit(value)
        require(
            url.scheme == "https"
            and url.hostname
            and "." in url.hostname
            and "@" not in url.netloc
            and not url.query
            and not url.fragment
            and url.port not in (2379, 2380, 2381, 2382, 6443, 6444),
            "unsupported workload check URL",
        )
        try:
            ipaddress.ip_address(url.hostname)
        except ValueError:
            pass
        else:
            raise Refused("workload check requires stable DNS hostname")


def _admit(bundle, catalog):
    """Pure validator: all paths below are strings in supplied evidence, never opened."""
    shape(
        bundle,
        {
            "schema_version",
            "source_revision",
            "capture_id",
            "enrollment_json",
            "observed",
            "directories",
            "layout",
            "health",
            "backup",
            "journals",
            "quiescence",
            "identity",
            "state_metadata",
        },
        "unsupported evidence schema",
    )
    require(
        type(bundle["schema_version"]) is int and bundle["schema_version"] == 1,
        "unsupported evidence version",
    )
    require(
        bundle["source_revision"] == catalog["revisions"]["source"], "unsupported source revision"
    )
    fingerprint(bundle["capture_id"])
    e = parse(bundle["enrollment_json"])
    enrollment_check(e)
    require(
        bundle["identity"]
        == {
            key: e[key]
            for key in ("machine_id_sha256", "systemd_sha256", "local_database", "k3s_version")
        },
        "captured machine/database/systemd identity mismatch",
    )
    state_files = {
        "/etc/rancher/k3s/sugarkube-recovery.json": sha(bundle["enrollment_json"].encode()),
        "/var/lib/sugarkube/ethernet-recovery/incident.json": sha(
            bundle["journals"]["incident_json"].encode()
        ),
        "/var/lib/sugarkube/ethernet-recovery/node-address.json": None,
    }
    shape(bundle["state_metadata"], state_files, "incomplete captured state metadata")
    for path, digest in state_files.items():
        metadata(bundle["state_metadata"][path], digest, "absent" if digest is None else "file")
    layout = bundle["layout"]
    shape(
        layout,
        {"descriptor", "entries", "directory", "runtime_view_absent"},
        "unsupported resolver layout",
    )
    view = layout["descriptor"]
    shape(view, {"kind", "symlink", "uid", "gid"}, "unsupported target descriptor")
    require(
        all(view[k] == v for k, v in VIEW.items())
        and all(type(view[k]) is int and 0 <= view[k] < 2**32 for k in ("uid", "gid")),
        "unsupported target descriptor",
    )
    metadata(layout["directory"], None, "directory", view["uid"], view["gid"])
    require(layout["runtime_view_absent"] is True, "partial or interrupted installation")
    shape(
        layout["entries"],
        {"resolv.conf", "stub-resolv.conf", "io.systemd.Resolve", "io.systemd.Resolve.Monitor"},
        "unknown or incomplete resolver layout",
    )
    for name, record in layout["entries"].items():
        socket = name.startswith("io.")
        if not socket:
            fingerprint(record["sha256"])
        metadata(
            record,
            None if socket else record["sha256"],
            "socket" if socket else "file",
            view["uid"],
            view["gid"],
        )
    old = artifacts(catalog, e, "source", view)
    new = artifacts(catalog, e, "target", view)
    resolver_paths = {
        CONFIG,
        "/usr/local/libexec/sugarkube/ethernet_mdns_resolver.py",
        *[
            p
            for p in old
            if "25-sugarkube-resolver" in p
            or "21-sugarkube-resolver" in p
            or p.endswith("sugarkube-ethernet-dns.service")
        ],
    }
    require(
        all(e["files"].get(p) == old[p] for p in resolver_paths),
        "unsupported or modified enrolled resolver artifacts",
    )
    require(
        all(p not in old or digest == old[p] for p, digest in e["files"].items()),
        "modified owned artifact fingerprint",
    )
    expected = {**e["files"], **old}
    shape(bundle["observed"], expected, "incomplete or extra captured file inventory")
    directories = {str(parent) for p in state_files for parent in PurePosixPath(p).parents}
    directories.update({"/run", "/run/systemd"})
    for path, digest in expected.items():
        directories.update(str(p) for p in PurePosixPath(path).parents)
        metadata(
            bundle["observed"][path],
            digest,
            "absent" if digest is None else "file",
            digest_kind=KUBECONFIG_DIGEST_KIND if path == e["kubeconfig"] else "raw-sha256",
        )
    shape(bundle["directories"], directories, "incomplete parent metadata")
    for record in bundle["directories"].values():
        metadata(record, None, "directory")
    shape(
        bundle["quiescence"],
        {"timer_paused", "controller_idle", "mutation_state"},
        "missing quiescence evidence",
    )
    require(
        canonical(bundle["quiescence"])
        == canonical({"timer_paused": True, "controller_idle": True, "mutation_state": "none"}),
        "unresolved or unknown mutation",
    )
    health = bundle["health"]
    shape(
        health,
        {"capture_id", "cluster_id", "members", "responders", "lock_absent"},
        "missing healthy original-quorum evidence",
    )
    require(
        health["capture_id"] == bundle["capture_id"]
        and health["cluster_id"] == e["cluster_id"]
        and health["lock_absent"] is True,
        "inconsistent quorum capture or outstanding lock",
    )
    shape(health["members"], {m["id"] for m in e["members"]}, "original membership mismatch")
    addresses = set()
    for member in e["members"]:
        row = health["members"][member["id"]]
        shape(
            row,
            {
                "name",
                "hostname",
                "node_uid",
                "node_name",
                "ipv4",
                "internal_ip",
                "annotation_ip",
                "peer_urls",
                "ready",
                "learner",
                "marker_sha256",
            },
            "unsupported healthy member evidence",
        )
        require(
            all(row[k] == member[k] for k in ("name", "hostname", "node_uid"))
            and row["node_name"] == member["hostname"].removesuffix(".local"),
            "Node/member identity mismatch",
        )
        ipv4 = ipaddress.IPv4Address(row["ipv4"])
        require(
            not (
                ipv4.is_loopback or ipv4.is_unspecified or ipv4.is_multicast or ipv4.is_link_local
            ),
            "invalid peer address",
        )
        address = str(ipv4)
        require(
            address == row["ipv4"] == row["internal_ip"] == row["annotation_ip"]
            and row["ready"] is True
            and row["learner"] is False,
            "unhealthy or unconverged original Node",
        )
        require(
            row["peer_urls"] == [f"https://{address}:2380", f"https://{member['hostname']}:2380"],
            "numeric-only or changed peers need consensus review",
        )
        roster = sorted(e["members"], key=lambda m: m["id"])
        marker = {
            "schema_version": 2,
            "cluster_id": e["cluster_id"],
            "member_id": member["id"],
            "node_uid": member["node_uid"],
            "hostname": member["hostname"],
            "k3s_version": e["k3s_version"],
            "roster_sha256": sha(json.dumps(roster, sort_keys=True).encode()),
        }
        require(
            row["marker_sha256"] == sha(json.dumps(marker, sort_keys=True).encode()),
            "missing or conflicting original enrollment marker",
        )
        addresses.add(address)
    require(
        len(addresses) == 3 and health["members"][e["local_member_id"]]["ipv4"] == e["local_ipv4"],
        "duplicate or changed address",
    )
    shape(
        health["responders"], health["members"], "three original authenticated responders required"
    )
    for mid, response in health["responders"].items():
        require(
            canonical(response)
            == canonical(
                {
                    "cluster_id": e["cluster_id"],
                    "member_id": mid,
                    "members_sha256": sha(canonical(health["members"])),
                    "linearizable_read": True,
                    "peer_tls_verified": True,
                    "api_verified": True,
                    "membership_intent": "none",
                    "node_address_intent": "none",
                }
            ),
            "inconsistent quorum/API evidence",
        )
    backup = bundle["backup"]
    shape(
        backup,
        {
            "capture_id",
            "cluster_id",
            "enrollment_sha256",
            "members_sha256",
            "snapshot_sha256",
            "original_bundle_sha256",
            "verified",
        },
        "missing backup evidence",
    )
    require(
        backup["capture_id"] == bundle["capture_id"]
        and backup["cluster_id"] == e["cluster_id"]
        and backup["enrollment_sha256"] == sha(bundle["enrollment_json"].encode())
        and backup["members_sha256"] == sha(canonical(health["members"]))
        and backup["verified"] is True,
        "backup identity or capture mismatch",
    )
    for key in ("snapshot_sha256", "original_bundle_sha256"):
        fingerprint(backup[key])
    journals = bundle["journals"]
    shape(journals, {"incident_json", "node_address_json"}, "missing journal inventory")
    require(
        journals["node_address_json"] is None,
        "Node-address journal requires separate reconciliation review",
    )
    incident = parse(journals["incident_json"])
    fields = set(
        (
            "token phase created_at kind transport ip member_id cluster_id "
            "mutation_dispatched old_peer_urls"
        ).split()
    )
    if incident.get("mutation_dispatched") is True:
        fields |= {"before_members", "desired_peer_urls"}
    shape(incident, fields, "unknown journal schema or mutation")
    require(
        incident["phase"] == "complete"
        and incident["kind"] == "enrollment"
        and incident["transport"] == "not-needed"
        and type(incident["mutation_dispatched"]) is bool,
        "unresolved membership intent or unsupported recovery journal",
    )
    require(
        incident["member_id"] == e["local_member_id"]
        and incident["cluster_id"] == e["cluster_id"]
        and incident["ip"] == e["local_ipv4"],
        "journal identity mismatch",
    )
    local_urls = health["members"][e["local_member_id"]]["peer_urls"]
    require(
        incident["old_peer_urls"] in (local_urls, local_urls[:1]), "journal peer identity mismatch"
    )
    require(
        type(incident["token"]) is str
        and re.fullmatch(r"[0-9a-f]{32}", incident["token"])
        and type(incident["created_at"]) in (int, float)
        and incident["created_at"] > 0,
        "unsupported journal identifier or timestamp",
    )
    if incident["mutation_dispatched"]:
        require(incident["desired_peer_urls"] == local_urls, "unknown membership mutation target")
        shape(
            incident["before_members"],
            health["members"],
            "inconsistent completed mutation evidence",
        )
        for mid, row in health["members"].items():
            prior = incident["before_members"][mid]
            shape(
                prior,
                {"ID", "name", "isLearner", "peerURLs"},
                "unsupported completed mutation snapshot",
            )
            require(
                prior["ID"] == mid
                and prior["name"] == row["name"]
                and prior["isLearner"] is False
                and prior["peerURLs"] in (row["peer_urls"], row["peer_urls"][:1]),
                "inconsistent completed mutation evidence",
            )
        require(
            incident["before_members"][e["local_member_id"]]["peerURLs"]
            == incident["old_peer_urls"],
            "inconsistent original mutation peers",
        )
    transitions = [
        {
            "path": p,
            "old_sha256": old[p],
            "new_sha256": new[p],
            "enrolled_fingerprint": p in e["files"],
        }
        for p in sorted(old)
        if old[p] != new[p]
    ]
    # Commitments preserve secrets and unrelated paths without echoing their contents.
    preserved = {k: v for k, v in e.items() if k != "files"}
    preserved["files"] = {
        p: d for p, d in e["files"].items() if p not in {t["path"] for t in transitions}
    }
    target_enrollment = {
        **e,
        "resolver_view": view,
        "files": {p: new.get(p, digest) for p, digest in e["files"].items()},
    }
    return {
        "schema_version": 1,
        "eligible_for_plan": True,
        "authorized_to_execute": False,
        "evidence_kind": "operator-supplied, not live authenticated proof",
        "capture_sha256": sha(canonical(bundle)),
        "old_enrollment_sha256": sha(bundle["enrollment_json"].encode()),
        "new_enrollment_canonical_sha256": sha(canonical(target_enrollment)),
        "revisions": catalog["revisions"],
        "old_descriptor": None,
        "new_descriptor": view,
        "cluster_id": e["cluster_id"],
        "local_member_id": e["local_member_id"],
        "members": e["members"],
        "transitions": transitions,
        "preserved_enrollment_sha256": sha(canonical(preserved)),
        "journals_sha256": sha(canonical(journals)),
        "prerequisites": [
            "Separate reviewed execution procedure and authorization",
            "Fresh authenticated original-quorum, Node, backup and idle-controller proof",
            "One-server stop/activation with original identities and journals preserved",
            "Loaded-unit, real mount/IPC, pod DNS and workload checks before timer resume",
        ],
    }


def plan(bundle):
    try:
        raw = CATALOG.read_bytes()
        require(sha(raw) == CATALOG_SHA256, "unsupported artifact catalog")
        return _admit(bundle, parse(raw))
    except Refused:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError) as exc:
        raise Refused("malformed or unsupported captured evidence") from exc


def read_evidence(path):
    with open(path, "rb") as handle:
        return handle.read(8 * 1024 * 1024 + 1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", help="operator-supplied JSON bundle; '-' reads stdin")
    args = parser.parse_args(argv)
    try:
        raw = (
            sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
            if args.evidence == "-"
            else read_evidence(args.evidence)
        )
        require(len(raw) <= 8 * 1024 * 1024, "evidence exceeds size limit")
        result = plan(parse(raw))
    except (Refused, OSError) as exc:
        diagnostic = (
            str(exc)
            if isinstance(exc, Refused)
            else "cannot read supplied evidence or pinned catalog"
        )
        print(
            json.dumps(
                {
                    "eligible_for_plan": False,
                    "authorized_to_execute": False,
                    "diagnostic": diagnostic,
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
