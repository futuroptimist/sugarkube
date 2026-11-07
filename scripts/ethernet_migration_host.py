#!/usr/bin/env python3
"""Host adapter for an explicitly authorized migration, never an automatic repair.

The receipt attests remote host-local journal/quiescence and backup restore facts.
It does NOT authenticate those facts through etcd. Observable facts are rechecked.
No CLI invocation is part of the offline qualification of this source.
"""

import argparse
import base64
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
import secrets
import stat
import sys
import time
import types
from contextlib import contextmanager
from pathlib import Path

import yaml


def sibling(name, filename=None):
    """Load only the explicit adjacent source, including under Python -I."""
    path = Path(__file__).resolve().with_name(filename or name + ".py")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise RuntimeError("untrusted migration runtime")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plan = sibling("ethernet_migration_plan")
apply_module = sibling("ethernet_migration_apply")
recovery = sibling(
    "ethernet_quorum_recover",
    (
        "ethernet-quorum-recover.py"
        if Path(__file__).resolve().parent == Path("/usr/local/libexec/sugarkube")
        else "ethernet_quorum_recover.py"
    ),
)

STATE = "/var/lib/sugarkube/ethernet-recovery"
TIMER = "sugarkube-ethernet-recovery.timer"
WATCHER = "sugarkube-ethernet-recovery.service"
DNS = "sugarkube-ethernet-dns.service"


class Files:
    """Root-relative, no-symlink parent traversal and compare-before-replace writes."""

    def __init__(self, root="/", uid=0):
        self.root, self.uid = Path(root), uid

    @contextmanager
    def parent(self, path):
        plan.path_name(path)
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            self.trusted(os.fstat(fd))
            for part in Path(path).parts[1:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
                self.trusted(os.fstat(fd))
            yield fd, Path(path).name
        finally:
            os.close(fd)

    def trusted(self, info):
        plan.require(info.st_uid == self.uid and not info.st_mode & 0o022, "untrusted path")

    def read(self, path):
        with self.parent(path) as (parent, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, "rb") as handle:
                info = os.fstat(handle.fileno())
                self.trusted(info)
                plan.require(
                    stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                    "single-link regular file required",
                )
                plan.require(info.st_size <= 128 * 1024 * 1024, "input file too large")
                return handle.read()

    def digest(self, path, *, clock=time.monotonic, max_bytes=1 << 40, max_seconds=120):
        """Stream large backup evidence without treating it as a small JSON input."""
        started = clock()
        with self.parent(path) as (parent, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, "rb") as handle:
                before = os.fstat(handle.fileno())
                self.trusted(before)
                plan.require(
                    stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                    "single-link regular backup required",
                )
                plan.require(0 <= before.st_size <= max_bytes, "backup exceeds streaming bound")

                def identity(info):
                    return (
                        info.st_dev,
                        info.st_ino,
                        info.st_size,
                        info.st_mtime_ns,
                        info.st_ctime_ns,
                        info.st_uid,
                        info.st_gid,
                        info.st_mode,
                        info.st_nlink,
                    )

                digest = hashlib.sha256()
                remaining = before.st_size
                while remaining:
                    plan.require(
                        0 <= clock() - started <= max_seconds,
                        "backup verification time budget exceeded",
                    )
                    chunk = handle.read(min(1024 * 1024, remaining))
                    plan.require(bool(chunk), "backup truncated during verification")
                    digest.update(chunk)
                    remaining -= len(chunk)
                plan.require(not handle.read(1), "backup grew during verification")
                after = os.fstat(handle.fileno())
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                plan.require(
                    identity(before) == identity(after) == identity(current),
                    "backup changed during verification",
                )
                plan.require(
                    0 <= clock() - started <= max_seconds,
                    "backup verification time budget exceeded",
                )
                return digest.hexdigest()

    def metadata(self, path, digest_kind="raw-sha256"):
        with self.parent(path) as (parent, name):
            try:
                info = os.stat(name or ".", dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                return {
                    "kind": "absent",
                    "uid": 0,
                    "gid": 0,
                    "mode": 0,
                    "sha256": None,
                    "digest_kind": "none",
                }
        kinds = ((stat.S_ISREG, "file"), (stat.S_ISDIR, "directory"), (stat.S_ISSOCK, "socket"))
        kind = next((name for check, name in kinds if check(info.st_mode)), None)
        plan.require(kind is not None, "unsupported filesystem entry")
        digest = None
        if kind == "file":
            raw = self.read(path)
            digest = (
                plan.kubeconfig_inventory_digest(yaml.safe_load(raw))
                if digest_kind == plan.KUBECONFIG_DIGEST_KIND
                else plan.sha(raw)
            )
        return {
            "kind": kind,
            "uid": info.st_uid,
            "gid": info.st_gid,
            "mode": stat.S_IMODE(info.st_mode),
            "sha256": digest,
            "digest_kind": digest_kind if digest is not None else "none",
        }

    def create(self, path, data, mode=0o600):
        with self.parent(path) as (parent, name):
            fd = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=parent
            )
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.fsync(parent)

    def replace(self, path, old_digest, data, backup):
        # The exclusive controller lock protects cooperative writers. We also
        # compare the inode and contents immediately before atomic publication.
        with self.parent(path) as (parent, name):
            before = self.metadata(path)
            plan.require(
                before["kind"] == "file" and before["sha256"] == old_digest,
                "replacement baseline changed",
            )
            original = self.read(path)
            self.create(backup, original, before["mode"])
            self.create(
                backup + ".json",
                plan.canonical({"path": path, "metadata": before, "backup_path": backup}),
            )
            saved = os.stat(name, dir_fd=parent, follow_symlinks=False)
            temporary = ".migration-" + secrets.token_hex(16)
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                before["mode"],
                dir_fd=parent,
            )
            with os.fdopen(fd, "wb") as handle:
                os.fchmod(handle.fileno(), before["mode"])
                os.fchown(handle.fileno(), saved.st_uid, saved.st_gid)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            plan.require(
                (current.st_dev, current.st_ino) == (saved.st_dev, saved.st_ino)
                and self.read(path) == original,
                "replacement race",
            )
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
            plan.require(
                self.read(path) == data and self.metadata(path)["mode"] == before["mode"],
                "replacement readback failed",
            )


def validate_receipt(receipt, bundle, approved_plan, now):
    plan.shape(
        receipt,
        {
            "schema_version",
            "plan_sha256",
            "baseline_sha256",
            "issued_at",
            "expires_at",
            "gates",
            "remote_attestations",
            "backup",
            "backup_files",
            "pod_dns",
        },
        "unsupported operational receipt",
    )
    plan.require(
        receipt["schema_version"] == 1
        and receipt["plan_sha256"] == plan.sha(plan.canonical(approved_plan))
        and receipt["baseline_sha256"] == plan.sha(plan.canonical(bundle)),
        "receipt baseline/plan mismatch",
    )
    start, end = receipt["issued_at"], receipt["expires_at"]
    plan.require(
        type(start) in (int, float)
        and type(end) in (int, float)
        and start <= now < end
        and 0 < end - start <= 300,
        "expired or unbounded operational receipt",
    )
    plan.require(
        plan.canonical(receipt["gates"])
        == plan.canonical({gate: True for gate in apply_module.GATES}),
        "missing operational authorization",
    )
    e = plan.parse(bundle["enrollment_json"])
    expected = {
        m["id"]: {
            "timer_paused": True,
            "controller_idle": True,
            "membership_intent": "none",
            "node_address_intent": "none",
        }
        for m in e["members"]
    }
    plan.require(
        plan.canonical(receipt["remote_attestations"]) == plan.canonical(expected)
        and receipt["backup"] == bundle["backup"],
        "missing explicit operational evidence",
    )
    backup_files = receipt["backup_files"]
    plan.shape(
        backup_files,
        {
            "snapshot_path",
            "original_bundle_path",
            "restore_evidence_path",
            "restore_evidence_sha256",
        },
        "missing backup files",
    )
    for key in ("snapshot_path", "original_bundle_path", "restore_evidence_path"):
        plan.path_name(backup_files[key])
    plan.fingerprint(backup_files["restore_evidence_sha256"])
    probe = receipt["pod_dns"]
    plan.shape(
        probe,
        {"namespace", "pod", "uid", "container", "hostname", "expected_ipv4"},
        "missing existing pod DNS probe",
    )
    import re

    for key in ("namespace", "pod", "container", "hostname"):
        plan.require(
            type(probe[key]) is str and re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,252}", probe[key]),
            "invalid DNS probe selector",
        )
    plan.require(type(probe["uid"]) is str and bool(probe["uid"]), "missing probe pod identity")
    import ipaddress

    plan.require(
        str(ipaddress.IPv4Address(probe["expected_ipv4"])) == probe["expected_ipv4"],
        "invalid expected DNS answer",
    )


class HostBackend:
    def __init__(
        self,
        bundle,
        approved_plan,
        receipt,
        files=None,
        backend=None,
        wall=time.time,
        backend_factory=None,
    ):
        self.bundle, self.plan, self.receipt = copy.deepcopy((bundle, approved_plan, receipt))
        self.files = files or Files()
        self.e = plan.parse(bundle["enrollment_json"])
        self.backend = backend or self.installed_backend(self.e, target=False)
        self.backend_factory = backend_factory or self.installed_backend
        self.wall = wall
        self.owner = None
        self.lock = None
        self.written = {}
        self.sequence = 0
        validate_receipt(receipt, bundle, approved_plan, wall())

    def installed_backend(self, enrollment, target=True):
        """Execute only the exact fixed installed source/target controller bytes."""
        plan.require(self.files.root == Path("/"), "production backend requires actual host root")
        raw_catalog = apply_module.CATALOG.read_bytes()
        plan.require(
            plan.sha(raw_catalog) == apply_module.CATALOG_SHA256,
            "unsupported guarded artifact catalog",
        )
        catalog = plan.parse(raw_catalog)
        path = "/usr/local/libexec/sugarkube/ethernet-quorum-recover.py"
        raw = self.files.read(path)
        expected = catalog["artifacts"]["target" if target else "source"]["runtime_sha256"][path]
        plan.require(plan.sha(raw) == expected, "installed controller differs from pinned phase")
        # Compile the bytes already verified, not a second path read vulnerable
        # to replacement. Its explicit __file__ anchors all installed siblings.
        module = types.ModuleType("sugarkube_migration_installed_controller")
        module.__file__ = path
        exec(compile(raw, path, "exec"), module.__dict__)
        return module.Backend(enrollment)

    def command(self, *args):
        return self.backend.command(["/usr/bin/systemctl", *args])

    def inactive(self, unit):
        value = self.command("show", unit, "--property=ActiveState,SubState")
        props = dict(line.split("=", 1) for line in value.splitlines() if "=" in line)
        plan.require(
            props.get("ActiveState") == "inactive" and props.get("SubState") == "dead",
            "service not stopped and idle",
        )

    @contextmanager
    def exclusive_local_lock(self):
        with self.files.parent(STATE + "/lock") as (parent, name):
            fd = os.open(
                name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent
            )
        info = os.fstat(fd)
        self.files.trusted(info)
        plan.require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "untrusted lock file")
        self.lock = fd
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)
            self.lock = None
            self.backend.close()

    def check_gates(self, gates):
        plan.require(gates == apply_module.GATES, "unknown operational gates")
        validate_receipt(self.receipt, self.bundle, self.plan, self.wall())
        evidence = self.receipt["backup_files"]
        for path_key, digest in (
            ("snapshot_path", self.bundle["backup"]["snapshot_sha256"]),
            ("original_bundle_path", self.bundle["backup"]["original_bundle_sha256"]),
            ("restore_evidence_path", evidence["restore_evidence_sha256"]),
        ):
            plan.require(
                self.files.digest(evidence[path_key]) == digest,
                "backup or restore evidence changed",
            )
        self.inactive(TIMER)
        self.inactive(WATCHER)

    def local_capture(self, fresh):
        for section in ("observed", "directories", "state_metadata"):
            for path, expected in fresh[section].items():
                actual = self.files.metadata(path, expected["digest_kind"])
                plan.require(actual == expected, "local captured metadata drift")
        plan.require(
            self.files.read(apply_module.ENROLLMENT).decode() == fresh["enrollment_json"],
            "enrollment drift",
        )
        plan.require(
            self.files.read(STATE + "/incident.json").decode()
            == fresh["journals"]["incident_json"],
            "journal drift",
        )
        layout = fresh["layout"]
        plan.require(
            self.files.metadata("/run/systemd/resolve") == layout["directory"],
            "resolver directory changed",
        )
        for name, expected in layout["entries"].items():
            plan.require(
                self.files.metadata("/run/systemd/resolve/" + name) == expected,
                "resolver entry changed",
            )
        plan.require(
            self.files.metadata("/run/sugarkube-ethernet-dns/resolved")["kind"] == "absent",
            "partial directory-view migration",
        )
        self.backend.config()

    def remote_proof(self, expected_lock=None):
        members = self.bundle["health"]["members"]
        expected_members = {
            mid: {"ID": mid, "name": row["name"], "peerURLs": row["peer_urls"]}
            for mid, row in members.items()
        }
        for member in self.e["members"]:
            host, mid = member["hostname"], member["id"]
            row = members[mid]
            plan.require(self.backend.resolve(host) == row["ipv4"], "peer address changed")
            self.backend.peer_tls(host)
            status = self.backend.etcd(host, "endpoint", "status")[0]["Status"]
            plan.require(
                str(status["header"]["cluster_id"]) == self.e["cluster_id"]
                and str(status["header"]["member_id"]) == mid
                and not status.get("errors")
                and not status.get("isLearner", False),
                "unhealthy original responder",
            )
            plan.require(
                self.backend.etcd(host, "endpoint", "health") == [{"health": True}],
                "linearizable quorum read failed",
            )
            result = self.backend.etcd(host, "member", "list")
            actual = {}
            for item in result["members"]:
                key = str(item["ID"])
                plan.require(
                    key not in actual and not item.get("isLearner", False), "membership ambiguity"
                )
                actual[key] = {"ID": key, "name": item["name"], "peerURLs": item["peerURLs"]}
            plan.require(actual == expected_members, "original membership changed")
            node = self.backend.node(host, row["node_name"])
            annotations = node["metadata"].get("annotations", {})
            internal = [
                a["address"]
                for a in node["status"].get("addresses", [])
                if a["type"] == "InternalIP"
            ]
            plan.require(
                node["metadata"]["uid"] == row["node_uid"]
                and node["metadata"]["name"] == row["node_name"]
                and annotations.get("k3s.io/internal-ip") == row["annotation_ip"]
                and annotations.get("etcd.k3s.cattle.io/node-name") == row["name"]
                and internal == [row["internal_ip"]]
                and any(
                    c.get("type") == "Ready" and c.get("status") == "True"
                    for c in node["status"].get("conditions", [])
                ),
                "Node drift",
            )
            for enrolled in self.e["members"]:
                values = self.backend.etcd(
                    host, "get", recovery.KEY + "/enrollment/" + enrolled["id"]
                ).get("kvs", [])
                plan.require(
                    len(values) == 1
                    and plan.sha(base64.b64decode(values[0]["value"], validate=True))
                    == members[enrolled["id"]]["marker_sha256"],
                    "enrollment marker drift",
                )
            values = self.backend.etcd(host, "get", recovery.KEY).get("kvs", [])
            actual_lock = (
                None if not values else base64.b64decode(values[0]["value"], validate=True).decode()
            )
            plan.require(
                len(values) <= 1 and actual_lock == expected_lock, "membership lock changed"
            )

    def capture(self, nonce):
        self.check_gates(frozenset(apply_module.GATES))
        fresh = copy.deepcopy(self.bundle)
        self.local_capture(fresh)
        self.remote_proof()
        for container in (fresh, fresh["health"], fresh["backup"]):
            container["capture_id"] = nonce
        # Remote journal facts and restored backup remain explicitly attested;
        # only the independently observed fields above receive fresh proof.
        return fresh

    def transaction(self, owner, release=False):
        lock_value = plan.canonical(owner).decode()
        compare = {
            "key": recovery.encode(recovery.KEY),
            "target": "VALUE" if release else "VERSION",
            "result": "EQUAL",
            "value" if release else "version": recovery.encode(lock_value) if release else "0",
        }
        operation = {"key": recovery.encode(recovery.KEY)}
        if not release:
            operation["value"] = recovery.encode(lock_value)
        payload = {
            "compare": [compare],
            "success": [{"request_delete_range" if release else "request_put": operation}],
            "failure": [],
        }
        host = next(
            m["hostname"] for m in self.e["members"] if m["id"] != self.e["local_member_id"]
        )
        result = self.backend.etcd(host, "txn", input_text=json.dumps(payload))
        plan.require(
            result.get("succeeded") is True, "cluster ownership CAS failed; reconcile intent"
        )

    def acquire_cluster_lock(self, owner):
        self.owner = owner
        self.transaction(owner)

    def reprove_under_lock(self, bundle, owner):
        self.check_gates(frozenset(apply_module.GATES))
        self.local_capture(bundle)
        self.remote_proof(plan.canonical(owner).decode())

    def stop_local_services(self):
        self.command("stop", "k3s.service")
        self.command("stop", DNS)
        self.backend.close()

    def verify_stopped_and_preserved(self, bundle):
        self.inactive("k3s.service")
        self.inactive(DNS)
        self.verify_no_consumers()
        plan.require(
            self.backend.local_database() == self.e["local_database"], "database identity drift"
        )
        for section in ("observed", "state_metadata"):
            for path, expected in bundle[section].items():
                plan.require(
                    self.files.metadata(path, expected["digest_kind"]) == expected,
                    "stopped inventory drift",
                )

    def verify_no_consumers(self):
        """Refuse residual shims/process namespaces; never kill workloads for migration."""
        proc = self.files.root / "proc"
        for entry in proc.iterdir():
            if not entry.name.isdigit() or int(entry.name) == os.getpid():
                continue
            try:
                command = (entry / "cmdline").read_bytes().replace(b"\0", b" ")
                mounts = (entry / "mountinfo").read_bytes()
            except FileNotFoundError:
                continue  # Process exited between enumeration and inspection.
            plan.require(
                not any(
                    process_name in command
                    for process_name in (
                        b"containerd",
                        b"k3s server",
                        b"k3s agent",
                        b"kubelet",
                        b"ethernet-quorum-recover.py",
                        b"ethernet_quorum_recover.py",
                        b"ethernet_mdns_resolver.py",
                    )
                )
                and b"sugarkube-ethernet-dns" not in mounts,
                "residual workload or resolver namespace requires operator stop",
            )

    def replace_file(self, path, old_digest, data):
        allowed = {t["path"]: t["old_sha256"] for t in self.plan["transitions"]}
        allowed[apply_module.ENROLLMENT] = self.plan["old_enrollment_sha256"]
        plan.require(
            path in allowed and allowed[path] == old_digest and path not in self.written,
            "unapproved replacement or replay",
        )
        self.sequence += 1
        backup = STATE + f"/migration-original-{self.sequence:04d}"
        self.files.replace(path, old_digest, data, backup)
        self.written[path] = plan.sha(data)

    def activate_local_services(self):
        plan.require(
            self.lock is not None and self.owner is not None, "missing migration ownership"
        )
        self.permit = {
            "schema_version": 1,
            "owner": self.owner,
            "target_enrollment_sha256": plan.sha(self.files.read(apply_module.ENROLLMENT)),
            "incident_sha256": plan.sha(self.files.read(STATE + "/incident.json")),
            "baseline_ipv4": self.e["local_ipv4"],
        }
        self.files.create(STATE + "/migration-start-permit.json", plan.canonical(self.permit))
        self.command("daemon-reload")
        # Hooks take the same flock. The durable guard, not the flock, protects
        # this interval, and the pre-start hook consumes exactly one permit.
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        try:
            self.command("start", DNS)
            self.command("start", "k3s.service")
        finally:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        consumed = plan.parse(self.files.read(STATE + "/migration-start-consumed.json"))
        plan.require(
            {k: v for k, v in consumed.items() if k != "invocation_id"} == self.permit
            and bool(consumed.get("invocation_id")),
            "one-start permit was not consumed",
        )
        new = plan.parse(self.files.read(apply_module.ENROLLMENT))
        self.backend = self.backend_factory(new)

    def verify_completion(self, approved_plan, checks):
        plan.require(
            checks == apply_module.CHECKS and approved_plan == self.plan, "unknown completion scope"
        )
        new = plan.parse(self.files.read(apply_module.ENROLLMENT))
        plan.require(
            plan.sha(plan.canonical(new)) == self.plan["new_enrollment_canonical_sha256"],
            "target enrollment changed",
        )
        self.backend.e = new
        for path, digest in self.written.items():
            plan.require(plan.sha(self.files.read(path)) == digest, "target artifact changed")
        for path, expected in self.bundle["observed"].items():
            if path not in self.written:
                plan.require(
                    self.files.metadata(path, expected["digest_kind"]) == expected,
                    "unrelated file changed",
                )
        for path, expected in self.bundle["state_metadata"].items():
            if path != apply_module.ENROLLMENT:
                plan.require(self.files.metadata(path) == expected, "journal changed")
        self.backend.config()  # includes loaded units, real namespace mounts and resolved IPC
        plan.require(
            self.backend.local_database() == self.e["local_database"], "database identity changed"
        )
        self.remote_proof(plan.canonical(self.owner).decode() if self.owner else None)
        self.pod_dns()
        self.backend.workloads(self.e["members"][0]["hostname"])

    def pod_dns(self):
        probe = self.receipt["pod_dns"]
        host = self.e["members"][0]["hostname"]
        base = [
            "/usr/local/bin/kubectl",
            f"--kubeconfig={self.e['kubeconfig']}",
            f"--server=https://{self.backend.resolve(host)}:6443",
            f"--tls-server-name={host}",
            "--request-timeout=5s",
            "--namespace=" + probe["namespace"],
        ]
        pod = plan.parse(self.backend.command(base + ["get", "pod", probe["pod"], "-o", "json"]))
        local = next(m for m in self.e["members"] if m["id"] == self.e["local_member_id"])
        plan.require(
            pod["metadata"]["uid"] == probe["uid"]
            and pod["spec"]["nodeName"] == local["hostname"].removesuffix(".local")
            and probe["container"] in {c["name"] for c in pod["spec"]["containers"]},
            "probe pod identity or placement changed",
        )
        output = self.backend.command(
            base
            + [
                "exec",
                probe["pod"],
                "-c",
                probe["container"],
                "--",
                "getent",
                "ahostsv4",
                probe["hostname"],
            ]
        )
        plan.require(
            {line.split()[0] for line in output.splitlines() if line.strip()}
            == {probe["expected_ipv4"]},
            "pod DNS answer changed",
        )

    def release_cluster_lock(self, owner):
        self.transaction(owner, release=True)
        self.owner = None
        self.files.create(STATE + "/migration-complete.json", plan.canonical(self.permit))

    def resume_timer(self):
        self.command("start", TIMER)

    def verify_timer_and_completion(self, approved_plan, checks):
        value = self.command("show", TIMER, "--property=ActiveState", "--value").strip()
        plan.require(value == "active", "timer not active")
        self.verify_completion(approved_plan, checks)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "capture", "apply"))
    parser.add_argument("--output", help="exclusive root-private output for plan/capture")
    for name in ("baseline", "plan", "receipt", "runtime_directory"):
        parser.add_argument("--" + name.replace("_", "-"), required=name == "baseline")
    args = parser.parse_args(argv)
    files = Files()
    try:
        plan.require(os.geteuid() == 0, "root operational execution required")
        bundle = plan.parse(files.read(args.baseline))
        if args.action == "plan":
            plan.require(args.output is not None, "private plan output required")
            approved_plan = apply_module.guarded_plan(bundle)
            files.create(args.output, plan.canonical(approved_plan))
            print("guarded plan written; operational authorization still required")
            return 0
        plan.require(
            args.plan is not None and args.receipt is not None,
            "approved plan and operational receipt required",
        )
        plan.require(files.metadata(args.receipt)["mode"] == 0o600, "root-private receipt required")
        approved_plan, receipt = [plan.parse(files.read(p)) for p in (args.plan, args.receipt)]
        plan.require(
            plan.canonical(apply_module.guarded_plan(bundle)) == plan.canonical(approved_plan),
            "approved guarded plan mismatch",
        )
        backend = HostBackend(bundle, approved_plan, receipt, files=files)
        if args.action == "capture":
            plan.require(args.output is not None, "private capture output required")
            with backend.exclusive_local_lock():
                capture = backend.capture(secrets.token_hex(32))
            files.create(args.output, plan.canonical(capture))
            print("private capture written; derive a new plan and receipt before apply")
            return 0
        plan.require(args.runtime_directory is not None, "pinned target runtime directory required")
        catalog = plan.parse(apply_module.CATALOG.read_bytes())
        runtime = {
            p: files.read(str(Path(args.runtime_directory) / Path(p).name))
            for p in catalog["artifacts"]["target"]["runtime_sha256"]
        }
        approval = {
            "plan_sha256": receipt["plan_sha256"],
            "expires_at": time.monotonic() + 30,
            "gates": receipt["gates"],
        }
        result = apply_module.apply(
            bundle, approved_plan, approval, runtime, backend, apply_module.IntentStore(STATE)
        )
        print(plan.canonical(result).decode())
        return 0
    except (
        plan.Refused,
        apply_module.planner.Refused,
        recovery.Stop,
        RuntimeError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ):
        print(
            "migration refused or outcome uncertain; preserve intent and reconcile manually",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
