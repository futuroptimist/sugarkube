"""Offline adapter tests. No services, sockets, credentials or real host execution."""

import base64
import copy
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ethernet_migration_host as H  # noqa: E402
import test_ethernet_migration_plan as fixtures  # noqa: E402
from test_ethernet_migration_apply import case as core_case  # noqa: E402,F401
from test_ethernet_migration_guard import Backend as GuardBackend  # noqa: E402


@pytest.fixture(autouse=True)
def forbid_live_subprocess(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline tests must inject lifecycle subprocess")

    monkeypatch.setattr(H.subprocess, "run", forbidden)


@pytest.fixture
def files(tmp_path):
    tmp_path.chmod(0o700)
    return H.Files(tmp_path, uid=os.geteuid())


def put(files, path, data=b"original", mode=0o640):
    p = files.root / path.lstrip("/")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    p.chmod(mode)
    return p


def receipt(bundle):
    return {
        "schema_version": 1,
        "plan_sha256": H.plan.sha(H.plan.canonical({})),
        "baseline_sha256": H.plan.sha(H.plan.canonical(bundle)),
        "issued_at": 100,
        "expires_at": 200,
        "gates": {g: True for g in H.apply_module.GATES},
        "remote_attestations": {
            m: {
                "timer_paused": True,
                "controller_idle": True,
                "membership_intent": "none",
                "node_address_intent": "none",
            }
            for m in bundle["health"]["members"]
        },
        "backup": copy.deepcopy(bundle["backup"]),
        "backup_files": {
            "snapshot_path": "/snapshot",
            "original_bundle_path": "/original",
            "restore_evidence_path": "/restore",
            "restore_evidence_sha256": "a" * 64,
        },
        "pod_dns": {
            "namespace": "test",
            "pod": "dns",
            "uid": "uid",
            "container": "main",
            "hostname": "example.test",
            "expected_ipv4": "192.0.2.1",
        },
    }


def test_root_metadata_and_original_byte_mode_backup(files):
    assert files.metadata("/")["kind"] == "directory"
    original = put(files, "/etc/test", b"original\n", 0o640)
    put(files, "/state/placeholder")
    files.replace("/etc/test", H.plan.sha(b"original\n"), b"new\n", "/state/backup")
    assert original.read_bytes() == b"new\n"
    assert original.stat().st_mode & 0o777 == 0o640
    assert files.read("/state/backup") == b"original\n"
    record = H.plan.parse(files.read("/state/backup.json"))
    assert record["path"] == "/etc/test"
    assert record["metadata"]["sha256"] == H.plan.sha(b"original\n")
    with pytest.raises(FileExistsError):
        files.create("/state/backup", b"overwrite")


def test_replacement_drift_does_not_create_backup(files):
    put(files, "/file", b"drift")
    with pytest.raises(H.plan.Refused, match="baseline"):
        files.replace("/file", H.plan.sha(b"original"), b"new", "/backup")
    assert not (files.root / "backup").exists()


@pytest.mark.parametrize("kind", ["leaf", "parent", "hardlink", "writable-root"])
def test_untrusted_paths_fail_closed(files, kind):
    original = put(files, "/safe/file")
    path = "/safe/file"
    if kind == "leaf":
        (files.root / "link").symlink_to(original)
        path = "/link"
    elif kind == "parent":
        (files.root / "link").symlink_to(original.parent, target_is_directory=True)
        path = "/link/file"
    elif kind == "hardlink":
        os.link(original, files.root / "hardlink")
    else:
        files.root.chmod(0o777)
    with pytest.raises((H.plan.Refused, OSError)):
        files.read(path)


@pytest.mark.parametrize(
    "change", ["plan", "baseline", "expiry", "unbounded", "remote", "backup", "probe"]
)
def test_receipt_is_bound_and_bounded(change):
    bundle = fixtures.sample()
    r = receipt(bundle)
    H.validate_receipt(r, bundle, {}, 150)
    if change in ("plan", "baseline"):
        r[change + "_sha256"] = "f" * 64
    elif change == "expiry":
        r["expires_at"] = 140
    elif change == "unbounded":
        r["expires_at"] = 500
    elif change == "remote":
        r["remote_attestations"]["2"]["membership_intent"] = "unknown"
    elif change == "backup":
        r["backup"]["snapshot_sha256"] = "0" * 64
    else:
        r["pod_dns"]["pod"] = "--help"
    with pytest.raises(H.plan.Refused):
        H.validate_receipt(r, bundle, {}, 150)


class FakeProbe:
    def __init__(self, bundle):
        self.bundle = bundle
        self.e = H.plan.parse(bundle["enrollment_json"])
        self.calls = []
        self.drift = None
        self.lock = None

    def network(self, ip):
        assert ip == self.e["local_ipv4"]

    def close(self):
        self.calls.append("close")

    def resolve(self, host):
        return next(
            row["ipv4"]
            for row in self.bundle["health"]["members"].values()
            if row["hostname"] == host
        )

    def peer_tls(self, host):
        self.calls.append(("tls", host))

    def node(self, host, name):
        row = next(
            row for row in self.bundle["health"]["members"].values() if row["node_name"] == name
        )
        return {
            "metadata": {
                "uid": "wrong" if self.drift == "node" else row["node_uid"],
                "name": name,
                "annotations": {
                    "k3s.io/internal-ip": row["ipv4"],
                    "etcd.k3s.cattle.io/node-name": row["name"],
                },
            },
            "status": {
                "addresses": [{"type": "InternalIP", "address": row["ipv4"]}],
                "conditions": [{"type": "Ready", "status": "True"}],
            },
        }

    def etcd(self, host, *args, input_text=None):
        self.calls.append((host, args))
        member = next(m for m in self.e["members"] if m["hostname"] == host)
        if args == ("endpoint", "status"):
            return [{"Status": {"header": {"cluster_id": "100", "member_id": member["id"]}}}]
        if args == ("endpoint", "health"):
            return [{"health": self.drift != "health"}]
        if args == ("member", "list"):
            rows = [
                {"ID": mid, "name": row["name"], "peerURLs": row["peer_urls"]}
                for mid, row in self.bundle["health"]["members"].items()
            ]
            if self.drift == "members":
                rows.pop()
            return {"members": rows}
        if args == ("get", H.recovery.KEY):
            return {"kvs": [] if self.lock is None else [{"value": H.recovery.encode(self.lock)}]}
        if args[0] == "get":
            enrolled = next(m for m in self.e["members"] if args[1].endswith("/" + m["id"]))
            marker = {
                "schema_version": 2,
                "cluster_id": "100",
                "member_id": enrolled["id"],
                "node_uid": enrolled["node_uid"],
                "hostname": enrolled["hostname"],
                "k3s_version": self.e["k3s_version"],
                "roster_sha256": H.plan.sha(
                    H.json.dumps(self.e["members"], sort_keys=True).encode()
                ),
            }
            raw = H.json.dumps(marker, sort_keys=True) if self.drift != "marker" else "wrong"
            return {"kvs": [{"value": H.recovery.encode(raw)}]}
        raise AssertionError(args)


def adapter(bundle, files):
    put(files, H.NETWORK, b"original-network-yaml", 0o640)
    fake = FakeProbe(bundle)
    return H.HostBackend(bundle, {}, receipt(bundle), files, fake, wall=lambda: 150), fake


@pytest.mark.parametrize("drift", [None, "node", "health", "members", "marker", "lock"])
def test_all_original_responders_and_observable_facts_are_reproved(files, drift):
    host, fake = adapter(fixtures.sample(), files)
    fake.drift = drift
    if drift == "lock":
        fake.lock = "other-owner"
    if drift:
        with pytest.raises(H.plan.Refused):
            host.remote_proof()
    else:
        host.remote_proof()
        assert len([c for c in fake.calls if c[0] == "tls"]) == 3
        fake.lock = "exact-owner"
        host.remote_proof("exact-owner")


@pytest.mark.parametrize(
    "content,mounts",
    [(b"containerd-shim", b""), (b"k3s server", b""), (b"other", b"/run/sugarkube-ethernet-dns")],
)
def test_residual_consumers_refuse_without_kill(files, content, mounts):
    put(files, "/proc/999999/cmdline", content)
    put(files, "/proc/999999/mountinfo", mounts)
    host, fake = adapter(fixtures.sample(), files)
    with pytest.raises(H.plan.Refused, match="residual"):
        host.verify_no_consumers()
    assert fake.calls == []


def test_empty_process_inventory_is_offline_only(files):
    (files.root / "proc").mkdir()
    host, _ = adapter(fixtures.sample(), files)
    host.verify_no_consumers()


def test_activation_permit_is_durable_before_unlocked_start(files, monkeypatch):
    bundle = fixtures.sample()
    host, fake = adapter(bundle, files)
    put(files, H.STATE + "/incident.json", bundle["journals"]["incident_json"].encode())
    put(files, H.apply_module.ENROLLMENT, bundle["enrollment_json"].encode())
    host.owner = {"operation_id": "a" * 64, "plan_sha256": "b" * 64}
    host.lock = 123
    locks, commands = [], []
    monkeypatch.setattr(H.fcntl, "flock", lambda fd, flags: locks.append(flags))
    host.backend_factory = lambda enrollment: fake

    def command(*args):
        commands.append(args)
        assert files.read(H.STATE + "/migration-start-permit.json")
        if args == ("start", "k3s.service"):
            assert locks == [H.fcntl.LOCK_UN]
            consumed = {**host.permit, "invocation_id": "test-invocation"}
            files.create(H.STATE + "/migration-start-consumed.json", H.plan.canonical(consumed))

    host.command = command
    host.activate_local_services()
    assert commands == [("daemon-reload",), ("start", H.DNS), ("start", "k3s.service")]
    assert locks == [H.fcntl.LOCK_UN, H.fcntl.LOCK_EX | H.fcntl.LOCK_NB]
    with pytest.raises(FileExistsError):
        host.activate_local_services()


def test_uncertain_start_reacquires_lock_and_keeps_permit(files, monkeypatch):
    bundle = fixtures.sample()
    host, _ = adapter(bundle, files)
    put(files, H.STATE + "/incident.json", bundle["journals"]["incident_json"].encode())
    put(files, H.apply_module.ENROLLMENT, bundle["enrollment_json"].encode())
    host.owner, host.lock = {"operation_id": "a" * 64, "plan_sha256": "b" * 64}, 123
    locks = []
    monkeypatch.setattr(H.fcntl, "flock", lambda fd, flags: locks.append(flags))

    def command(*args):
        if args == ("start", "k3s.service"):
            raise RuntimeError("uncertain")

    host.command = command
    with pytest.raises(RuntimeError, match="uncertain"):
        host.activate_local_services()
    assert files.read(H.STATE + "/migration-start-permit.json")
    assert not (files.root / (H.STATE + "/migration-complete.json").lstrip("/")).exists()
    assert locks[-1] == H.fcntl.LOCK_EX | H.fcntl.LOCK_NB


def test_failed_release_never_marks_complete(files):
    host, _ = adapter(fixtures.sample(), files)
    host.owner = {"operation_id": "a" * 64, "plan_sha256": "b" * 64}
    host.permit = {"test": True}

    def fail(*args, **kwargs):
        raise RuntimeError("uncertain CAS")

    host.transaction = fail
    with pytest.raises(RuntimeError, match="CAS"):
        host.release_cluster_lock(host.owner)
    assert host.owner is not None
    assert not (files.root / (H.STATE + "/migration-complete.json").lstrip("/")).exists()


def test_core_adapter_real_guard(core_case, files, monkeypatch):  # noqa: F811
    """Real intent/permit/consumption protocol with fake capture, services and peers."""
    bundle, approved, approval, runtime, _, _ = core_case
    r = receipt(bundle)
    r["plan_sha256"] = H.plan.sha(H.plan.canonical(approved))
    host = H.HostBackend(bundle, approved, r, files, FakeProbe(bundle), wall=lambda: 150)
    put(files, H.NETWORK, b"original-network-yaml", 0o640)
    state = files.root / H.STATE.lstrip("/")
    state.mkdir(parents=True)
    put(files, H.STATE + "/incident.json", bundle["journals"]["incident_json"].encode())
    put(files, H.apply_module.ENROLLMENT, bundle["enrollment_json"].encode())
    module = H.recovery
    monkeypatch.setattr(module, "trusted_file", lambda path: None)
    monkeypatch.setattr(module, "migration_service_context", lambda backend, phase: "a" * 32)
    # Reuse the core case's explicitly synthetic pinned catalog.
    from test_ethernet_migration_apply import A

    monkeypatch.setattr(H.apply_module, "CATALOG", A.CATALOG)
    monkeypatch.setattr(H.apply_module, "CATALOG_SHA256", A.CATALOG_SHA256)

    def capture(nonce):
        fresh = copy.deepcopy(bundle)
        for container in (fresh, fresh["health"], fresh["backup"]):
            container["capture_id"] = nonce
        return fresh

    host.capture = capture
    host.check_gates = lambda gates: None
    host.transaction = lambda owner, release=False: None
    host.reprove_under_lock = lambda bundle, owner: None
    host.stop_local_services = lambda: None
    host.verify_stopped_and_preserved = lambda bundle: None
    host.replace_file = lambda path, digest, data: put(files, path, data)
    completed_checks = []
    host.verify_completion = lambda approved, checks: completed_checks.append(checks)
    host.verify_timer_and_completion = lambda approved, checks: completed_checks.append(checks)
    host.backend_factory = lambda enrollment: FakeProbe(bundle)

    def command(*args):
        if args == ("start", "k3s.service"):
            enrollment = files.root / H.apply_module.ENROLLMENT.lstrip("/")
            e = H.plan.parse(enrollment.read_bytes())
            guard = GuardBackend(e, H.plan.canonical(host.owner).decode())
            assert (
                module.migration_start_guard(enrollment, guard, state, "pre-start")
                == "migration-start-authorized"
            )
            assert (
                module.migration_start_guard(enrollment, guard, state, "post-start")
                == "migration-start-observed"
            )

    host.command = command
    result = H.apply_module.apply(
        bundle,
        approved,
        approval,
        runtime,
        host,
        H.apply_module.IntentStore(state),
        clock=lambda: 100,
    )
    assert result["completed"]
    assert len(completed_checks) == 2
    assert (state / "migration-intent.json").exists()
    assert (state / "migration-start-consumed.json").exists()
    assert (state / "migration-complete.json").exists()
    assert (state / "incident.json").read_text() == bundle["journals"]["incident_json"]
    with pytest.raises(H.apply_module.planner.Refused, match="existing migration intent"):
        H.apply_module.apply(
            bundle,
            approved,
            approval,
            runtime,
            host,
            H.apply_module.IntentStore(state),
            clock=lambda: 100,
        )


def test_capture_refreshes_challenge_after_local_and_remote_checks(files, monkeypatch):
    bundle = fixtures.sample()
    host, fake = adapter(bundle, files)
    records = {
        p: r
        for section in ("observed", "directories", "state_metadata")
        for p, r in bundle[section].items()
    }
    records["/run/systemd/resolve"] = bundle["layout"]["directory"]
    records.update({"/run/systemd/resolve/" + p: r for p, r in bundle["layout"]["entries"].items()})
    records["/run/sugarkube-ethernet-dns/resolved"] = {"kind": "absent"}
    monkeypatch.setattr(files, "metadata", lambda path, *args: records[path])
    raw = {
        H.apply_module.ENROLLMENT: bundle["enrollment_json"].encode(),
        H.STATE + "/incident.json": bundle["journals"]["incident_json"].encode(),
        "/snapshot": b"snapshot",
        "/original": b"original",
        "/restore": b"restore",
    }
    for path, key in (("/snapshot", "snapshot_sha256"), ("/original", "original_bundle_sha256")):
        host.bundle["backup"][key] = H.plan.sha(raw[path])
    host.receipt = receipt(host.bundle)
    host.receipt["backup_files"]["restore_evidence_sha256"] = H.plan.sha(raw["/restore"])
    monkeypatch.setattr(files, "read", lambda path: raw[path])
    monkeypatch.setattr(files, "digest", lambda path: H.plan.sha(raw[path]))
    fake.config = lambda: fake.calls.append("config")
    fake.command = lambda argv: "ActiveState=inactive\nSubState=dead\n"
    fresh = host.capture("e" * 64)
    assert (
        fresh["capture_id"]
        == fresh["health"]["capture_id"]
        == fresh["backup"]["capture_id"]
        == "e" * 64
    )
    assert "config" in fake.calls
    host.owner = {"operation_id": "a" * 64, "plan_sha256": "b" * 64}
    fake.lock = H.plan.canonical(host.owner).decode()
    host.reprove_under_lock(host.bundle, host.owner)
    raw["/restore"] = b"changed"
    with pytest.raises(H.plan.Refused, match="backup"):
        host.check_gates(H.apply_module.GATES)


def test_stop_preservation_and_replace_dispatch(files, monkeypatch):
    bundle = fixtures.sample()
    host, fake = adapter(bundle, files)
    commands = []
    fake.command = lambda argv: commands.append(argv) or "ActiveState=inactive\nSubState=dead\n"
    host.lifecycle_runner = lambda argv, **kwargs: commands.append(
        argv
    ) or H.subprocess.CompletedProcess(argv, 0, "")
    host.stop_local_services()
    assert commands[:2] == [
        ["/usr/bin/systemctl", "stop", "k3s.service"],
        ["/usr/bin/systemctl", "stop", H.DNS],
    ]
    fake.local_database = lambda: host.e["local_database"]
    host.verify_no_consumers = lambda: None
    metadata = {
        p: r for section in ("observed", "state_metadata") for p, r in bundle[section].items()
    }
    monkeypatch.setattr(files, "metadata", lambda path, *args: metadata[path])
    host.verify_stopped_and_preserved(bundle)
    host.plan = {
        "transitions": [{"path": "/target", "old_sha256": "a" * 64}],
        "old_enrollment_sha256": "b" * 64,
    }
    replaced = []
    monkeypatch.setattr(files, "replace", lambda *args: replaced.append(args))
    host.replace_file("/target", "a" * 64, b"new")
    assert replaced[0][-1] == H.STATE + "/migration-original-0001"
    with pytest.raises(H.plan.Refused, match="replay"):
        host.replace_file("/target", "a" * 64, b"new")


def test_transaction_binds_exact_owner_and_cas_failure(files):
    host, fake = adapter(fixtures.sample(), files)
    calls = []
    owner = {"operation_id": "a" * 64, "plan_sha256": "b" * 64}

    def etcd(*args, input_text):
        calls.append(H.plan.parse(input_text))
        return {"succeeded": True}

    fake.etcd = etcd
    host.acquire_cluster_lock(owner)
    assert calls[0]["compare"][0]["version"] == "0"
    encoded = calls[0]["success"][0]["request_put"]["value"]
    assert base64.b64decode(encoded) == H.plan.canonical(owner)
    host.transaction(owner, release=True)
    assert calls[1]["compare"][0]["value"] == encoded
    fake.etcd = lambda *args, **kwargs: {"succeeded": False}
    with pytest.raises(H.plan.Refused, match="CAS"):
        host.transaction(owner)


@pytest.mark.parametrize("drift", [None, "uid", "placement", "answer"])
def test_existing_local_pod_dns_probe(files, drift):
    host, fake = adapter(fixtures.sample(), files)
    calls = []

    def command(argv):
        calls.append(argv)
        if "exec" in argv:
            return ("192.0.2.2" if drift == "answer" else "192.0.2.1") + " STREAM example.test\n"
        return H.json.dumps(
            {
                "metadata": {"uid": "wrong" if drift == "uid" else "uid"},
                "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
                "spec": {
                    "nodeName": "wrong" if drift == "placement" else "pi1",
                    "containers": [{"name": "main"}],
                },
            }
        )

    fake.command = command
    if drift:
        with pytest.raises(H.plan.Refused):
            host.pod_dns()
    else:
        host.pod_dns()
        assert calls[-1][-4:] == ["--", "getent", "ahostsv4", "example.test"]


@pytest.fixture
def completion_case(files, monkeypatch):
    bundle = fixtures.sample()
    host, fake = adapter(bundle, files)
    raw = bundle["enrollment_json"].encode()
    host.plan = {"new_enrollment_canonical_sha256": H.plan.sha(H.plan.canonical(host.e))}
    host.written = {"/target": H.plan.sha(b"target")}
    host.permit = {
        "schema_version": 1,
        "owner": {"operation_id": "a" * 64, "plan_sha256": "b" * 64},
    }
    host.consumed = {**host.permit, "invocation_id": "a" * 32}
    records = {
        H.apply_module.ENROLLMENT: raw,
        "/target": b"target",
        H.STATE + "/migration-intent.json": H.plan.canonical(host.permit),
        H.STATE + "/migration-start-permit.json": H.plan.canonical(host.permit),
        H.STATE + "/migration-start-consumed.json": H.plan.canonical(host.consumed),
    }
    monkeypatch.setattr(files, "read", lambda path: records[path])
    metadata = {
        p: r for section in ("observed", "state_metadata") for p, r in bundle[section].items()
    }
    monkeypatch.setattr(files, "metadata", lambda path, *args: metadata[path])
    checked = []
    fake.config = lambda: checked.append("config")
    fake.local_database = lambda: host.e["local_database"]
    fake.workloads = lambda host: checked.append("workloads")
    fake.command = lambda argv: "a" * 32 if "--property=InvocationID" in argv else "active\n"
    host.pod_dns = lambda: checked.append("pod")
    return host, fake, checked, records


def test_completion_checks_target_preservation_and_timer(completion_case):
    host, fake, checked, records = completion_case
    host.verify_completion(host.plan, H.apply_module.CHECKS)
    host.lifecycle_runner = lambda argv, **kwargs: H.subprocess.CompletedProcess(argv, 0, "")
    host.resume_timer()
    host.verify_timer_and_completion(host.plan, H.apply_module.CHECKS)
    assert checked == ["config", "pod", "workloads"] * 2


def test_cli_plan_capture_apply_use_only_injected_files_and_backend(files, monkeypatch):
    bundle = fixtures.sample()
    r = receipt(bundle)
    data = {"/baseline": H.plan.canonical(bundle), "/plan": b"{}", "/receipt": H.plan.canonical(r)}
    monkeypatch.setattr(H, "Files", lambda: files)
    monkeypatch.setattr(H.os, "geteuid", lambda: 0)
    original_metadata = files.metadata
    monkeypatch.setattr(
        files,
        "metadata",
        lambda path, *args: (
            {"mode": 0o600} if path == "/receipt" else original_metadata(path, *args)
        ),
    )
    original_read = files.read
    monkeypatch.setattr(
        files, "read", lambda path: data[path] if path in data else original_read(path)
    )
    monkeypatch.setattr(H.apply_module, "guarded_plan", lambda bundle: {})
    assert H.main(["plan", "--baseline", "/baseline", "--output", "/out-plan"]) == 0
    assert H.main(["capture", "--baseline", "/baseline"]) == 2
    host, fake = adapter(bundle, files)
    host.capture = lambda nonce: bundle
    monkeypatch.setattr(H, "HostBackend", lambda *args, **kwargs: host)
    (files.root / H.STATE.lstrip("/")).mkdir(parents=True)
    assert (
        H.main(
            [
                "capture",
                "--baseline",
                "/baseline",
                "--plan",
                "/plan",
                "--receipt",
                "/receipt",
                "--output",
                "/out-capture",
            ]
        )
        == 0
    )
    catalog = H.plan.parse(H.apply_module.CATALOG.read_bytes())
    for path in catalog["artifacts"]["target"]["runtime_sha256"]:
        data["/runtime/" + Path(path).name] = b"fake"
    monkeypatch.setattr(H.apply_module, "apply", lambda *args: {"completed": True})
    assert (
        H.main(
            [
                "apply",
                "--baseline",
                "/baseline",
                "--plan",
                "/plan",
                "--receipt",
                "/receipt",
                "--runtime-directory",
                "/runtime",
            ]
        )
        == 0
    )


def test_installed_backend_executes_only_fixed_path_pinned_bytes(files, monkeypatch, tmp_path):
    host, _ = adapter(fixtures.sample(), files)
    with pytest.raises(H.plan.Refused, match="actual host root"):
        host.installed_backend(host.e)
    raw = (
        b"class Stop(RuntimeError): pass\nclass Backend:\n"
        b"    def __init__(self, enrollment):\n        self.e = enrollment\n"
    )
    controller = "/usr/local/libexec/sugarkube/ethernet-quorum-recover.py"
    catalog = {
        "artifacts": {
            phase: {"runtime_sha256": {controller: H.plan.sha(raw)}}
            for phase in ("source", "target")
        }
    }
    path = tmp_path / "catalog.json"
    path.write_bytes(H.plan.canonical(catalog))
    monkeypatch.setattr(H.apply_module, "CATALOG", path)
    monkeypatch.setattr(H.apply_module, "CATALOG_SHA256", H.plan.sha(path.read_bytes()))
    files.root = Path("/")
    reads = []
    monkeypatch.setattr(files, "read", lambda path: reads.append(path) or raw)
    assert host.installed_backend(host.e, target=False).e == host.e
    assert host.installed_backend(host.e, target=True).e == host.e
    assert reads == [controller, controller]
    monkeypatch.setattr(files, "read", lambda path: b"raise AssertionError('must not execute')")
    with pytest.raises(H.plan.Refused, match="pinned phase"):
        host.installed_backend(host.e)


def test_absent_metadata_is_explicit(files):
    record = files.metadata("/absent")
    assert record == {
        "kind": "absent",
        "uid": 0,
        "gid": 0,
        "mode": 0,
        "sha256": None,
        "digest_kind": "none",
    }


def test_untrusted_sibling_is_not_executed(tmp_path, monkeypatch):
    runtime = tmp_path / "unsafe.py"
    runtime.write_text("raise AssertionError('must not execute')")
    runtime.chmod(0o666)
    monkeypatch.setattr(H, "__file__", str(tmp_path / "ethernet_migration_host.py"))
    with pytest.raises(RuntimeError, match="untrusted migration runtime"):
        H.sibling("unsafe")


def test_consumer_scan_ignores_self_and_exited_processes(files):
    proc = files.root / "proc"
    proc.mkdir()
    (proc / "self").mkdir()
    (proc / str(os.getpid())).mkdir()
    (proc / "999999").mkdir()  # Gone before cmdline could be read.
    host, fake = adapter(fixtures.sample(), files)
    host.verify_no_consumers()
    assert fake.calls == []


def test_entrypoint_help_does_not_touch_host(monkeypatch):
    import runpy

    monkeypatch.setattr(sys, "argv", [H.__file__, "--help"])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(H.__file__, run_name="__main__")
    assert result.value.code == 0


def test_backup_digest_streams_multiple_chunks_and_exceeds_small_input_limit(files):
    path = put(files, "/large-backup", b"")
    size = 128 * 1024 * 1024 + 1
    with path.open("wb") as handle:
        handle.truncate(size)  # Sparse, offline-only fixture; no large allocation.
    expected = H.hashlib.sha256()
    for _ in range(128):
        expected.update(bytes(1024 * 1024))
    expected.update(b"\0")
    with pytest.raises(H.plan.Refused, match="input file too large"):
        files.read("/large-backup")
    assert files.digest("/large-backup") == expected.hexdigest()
    assert files.digest("/large-backup", max_bytes=size) == expected.hexdigest()
    with pytest.raises(H.plan.Refused, match="streaming bound"):
        files.digest("/large-backup", max_bytes=size - 1)


@pytest.mark.parametrize("change", ["truncate", "grow", "overwrite", "replace", "mode"])
def test_backup_digest_refuses_in_read_drift(files, monkeypatch, change):
    path = put(files, "/backup", b"original")
    trusted = files.trusted
    changed = False

    def mutate_after_open(info):
        nonlocal changed
        trusted(info)
        if H.stat.S_ISREG(info.st_mode) and not changed:
            changed = True
            if change == "truncate":
                path.write_bytes(b"")
            elif change == "grow":
                path.write_bytes(b"original-more")
            elif change == "overwrite":
                path.write_bytes(b"modified")
            elif change == "replace":
                path.rename(path.with_name("prior"))
                path.write_bytes(b"original")
            else:
                path.chmod(0o600)

    monkeypatch.setattr(files, "trusted", mutate_after_open)
    with pytest.raises(H.plan.Refused, match="backup (truncated|grew|changed)"):
        files.digest("/backup")


@pytest.mark.parametrize("times", [[0, 121], [0, -1], [0, 0, 121], [0, 0, -1]])
def test_backup_digest_enforces_deadline_before_and_after_reads(files, times):
    put(files, "/backup", b"x")
    ticks = iter(times)
    with pytest.raises(H.plan.Refused, match="time budget"):
        files.digest("/backup", clock=lambda: next(ticks))


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_backup_digest_rejects_untrusted_file_types(files, kind):
    path = put(files, "/original", b"x")
    if kind == "symlink":
        (files.root / "backup").symlink_to(path)
    elif kind == "hardlink":
        os.link(path, files.root / "backup")
    else:
        os.mkfifo(files.root / "backup", 0o600)
    with pytest.raises((H.plan.Refused, OSError)):
        files.digest("/backup")


def test_empty_backup_digest(files):
    put(files, "/backup", b"")
    assert files.digest("/backup") == H.plan.sha(b"")


def test_earlier_network_hook_drift_keeps_backup_and_guard_blocks_recovery(files, monkeypatch):
    bundle = fixtures.sample()
    host, fake = adapter(bundle, files)
    original = (
        b'# Managed by configure_k3s_node_ip.sh\nnode-ip: "192.0.2.1"\n' b'flannel-iface: "eth0"\n'
    )
    put(files, H.NETWORK, original, 0o640)
    put(files, H.STATE + "/incident.json", bundle["journals"]["incident_json"].encode())
    enrollment = put(files, H.apply_module.ENROLLMENT, bundle["enrollment_json"].encode())
    state = files.root / H.STATE.lstrip("/")
    host.owner = {"operation_id": "a" * 64, "plan_sha256": "b" * 64}
    host.lock = 123
    intent = {
        "schema_version": 1,
        "owner": host.owner,
        "plan_sha256": host.owner["plan_sha256"],
        "target_enrollment_sha256": H.plan.sha(enrollment.read_bytes()),
        "incident_sha256": H.plan.sha(bundle["journals"]["incident_json"].encode()),
        "baseline_ipv4": "192.0.2.1",
        "cluster_id": "100",
        "local_member_id": "1",
    }
    H.apply_module.IntentStore(state).reserve(intent)
    monkeypatch.setattr(H.fcntl, "flock", lambda fd, flags: None)
    monkeypatch.setattr(H.recovery, "trusted_file", lambda path: None)
    monkeypatch.setattr(H.recovery, "migration_service_context", lambda backend, phase: "a" * 32)
    guard = GuardBackend(host.e, H.plan.canonical(host.owner).decode())
    hooks, normal_recovery = [], []

    def command(*args):
        if args == ("start", "k3s.service"):
            # systemd executes20-sugarkube-network before30-quorum-recovery.
            hooks.append("20-network-refresh")
            put(files, H.NETWORK, original.replace(b"192.0.2.1", b"192.0.2.99"), 0o640)
            guard.ip = "192.0.2.99"
            hooks.append("30-migration-guard")
            result = H.recovery.migration_start_guard(enrollment, guard, state, "pre-start")
            if result is None:
                normal_recovery.append("must-not-run")

    host.command = command
    with pytest.raises(H.recovery.Stop, match="migration baseline changed"):
        host.activate_local_services()
    assert hooks == ["20-network-refresh", "30-migration-guard"]
    assert normal_recovery == [] and guard.calls == []
    assert files.read(H.STATE + "/migration-network-original") == original
    record = H.plan.parse(files.read(H.STATE + "/migration-network-original.json"))
    assert record["owner"] == host.owner and record["path"] == H.NETWORK
    assert record["metadata"]["mode"] == 0o640
    assert record["metadata"]["sha256"] == H.plan.sha(original)
    assert files.read(H.NETWORK) != original  # No automatic rollback.
    assert (state / "migration-intent.json").exists()
    assert (state / "migration-start-permit.json").exists()
    assert not (state / "migration-start-consumed.json").exists()
    assert not (state / "migration-complete.json").exists()
    assert (state / "incident.json").read_text() == bundle["journals"]["incident_json"]


def test_network_backup_failure_precedes_start_permit(files, monkeypatch):
    host, fake = adapter(fixtures.sample(), files)
    host.owner = {"operation_id": "a" * 64, "plan_sha256": "b" * 64}
    host.lock = 123
    (files.root / H.STATE.lstrip("/")).mkdir(parents=True)
    original_metadata = files.metadata
    reads = 0

    def drift(path, *args):
        nonlocal reads
        record = original_metadata(path, *args)
        if path == H.NETWORK:
            reads += 1
            if reads > 1:
                record["sha256"] = "0" * 64
        return record

    monkeypatch.setattr(files, "metadata", drift)
    with pytest.raises(H.plan.Refused, match="before backup"):
        host.activate_local_services()
    assert not (files.root / H.STATE.lstrip("/") / "migration-start-permit.json").exists()
    assert fake.calls == []


@pytest.mark.parametrize(
    "operation,duration",
    [(("start", "k3s.service"), 65), (("stop", "k3s.service"), 90), (("start", H.DNS), 20)],
)
def test_lifecycle_allows_valid_jobs_longer_than_probe_timeout(files, operation, duration):
    host, _ = adapter(fixtures.sample(), files)
    now, calls = [0], []
    host.lifecycle_clock = lambda: now[0]

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        now[0] += duration
        return H.subprocess.CompletedProcess(argv, 0, "done")

    host.lifecycle_runner = run
    assert host.command(*operation) == "done"
    assert calls[0][1]["timeout"] == H.LIFECYCLE_TIMEOUTS[operation]
    assert set(calls[0][1]["env"]) == {"PATH"}
    assert calls[0][1]["check"] is True
    with pytest.raises(H.plan.Refused, match="replay"):
        host.command(*operation)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "failure,diagnostic",
    [
        ("timeout", "outcome uncertain"),
        ("failed", "job failed"),
        ("os", "dispatch uncertain"),
        ("late", "deadline exceeded"),
    ],
)
def test_lifecycle_unknown_or_failed_jobs_are_never_replayed(files, failure, diagnostic):
    host, _ = adapter(fixtures.sample(), files)
    now, calls = [0], []
    host.lifecycle_clock = lambda: now[0]

    def run(argv, **kwargs):
        calls.append(argv)
        if failure == "timeout":
            raise H.subprocess.TimeoutExpired(argv, kwargs["timeout"])
        if failure == "failed":
            raise H.subprocess.CalledProcessError(1, argv)
        if failure == "os":
            raise OSError("dispatch status unknown")
        now[0] += kwargs["timeout"] + 1
        return H.subprocess.CompletedProcess(argv, 0, "late")

    host.lifecycle_runner = run
    with pytest.raises(H.plan.Refused, match=diagnostic):
        host.command("start", "k3s.service")
    with pytest.raises(H.plan.Refused, match="replay"):
        host.command("start", "k3s.service")
    with pytest.raises(H.plan.Refused, match="failure latched"):
        host.command("daemon-reload")
    assert len(calls) == 1


def test_cumulative_lifecycle_budget_bounds_next_mutation(files):
    host, _ = adapter(fixtures.sample(), files)
    now, timeouts = [0], []
    host.lifecycle_clock = lambda: now[0]

    def run(argv, **kwargs):
        timeouts.append(kwargs["timeout"])
        now[0] += kwargs["timeout"]
        return H.subprocess.CompletedProcess(argv, 0, "")

    host.lifecycle_runner = run
    host.command("start", "k3s.service")  # 420 seconds consumed.
    now[0] += 170  # Includes read-only convergence/check time.
    host.command("start", H.TIMER)  # Remaining10 seconds, not a new30-second budget.
    assert timeouts == [420, 10]
    with pytest.raises(H.plan.Refused, match="total budget"):
        host.command("daemon-reload")
    assert len(timeouts) == 2
    assert ("daemon-reload",) not in host.lifecycle_attempts


@pytest.mark.parametrize("operation", [("restart", "k3s.service"), ("start", "other.service"), ()])
def test_dispatcher_rejects_unapproved_systemctl_operations(files, operation):
    host, _ = adapter(fixtures.sample(), files)
    with pytest.raises(H.plan.Refused, match="unsupported"):
        host.command(*operation)
    assert not host.lifecycle_attempts


def completion_clock(host):
    now = [0]
    host.completion_clock = lambda: now[0]
    host.completion_sleep = lambda seconds: now.__setitem__(0, now[0] + seconds)
    return now


def test_transient_node_readiness_rechecks_full_attempt_then_succeeds(completion_case, monkeypatch):
    host, fake, checked, records = completion_case
    completion_clock(host)
    original_node, calls = fake.node, []
    reads = []
    monkeypatch.setattr(host.files, "read", lambda path: reads.append(path) or records[path])

    def node(endpoint, name):
        calls.append(name)
        row = original_node(endpoint, name)
        if len(calls) <= 3:
            row["status"]["conditions"][0]["status"] = "False"
        return row

    fake.node = node
    host.verify_completion(host.plan, H.apply_module.CHECKS)
    assert len(calls) == 6
    assert checked.count("config") == 2
    assert reads.count(H.STATE + "/migration-intent.json") == 2
    assert reads.count(H.STATE + "/migration-start-consumed.json") == 2
    assert not host.lifecycle_attempts


def test_unready_node_never_masks_later_identity_drift(files):
    host, fake = adapter(fixtures.sample(), files)
    original = fake.node

    def node(endpoint, name):
        row = original(endpoint, name)
        if name == "pi1":
            row["status"]["conditions"][0]["status"] = "False"
        if name == "pi2":
            row["metadata"]["uid"] = "changed"
        return row

    fake.node = node
    with pytest.raises(H.plan.Refused, match="Node drift") as error:
        host.remote_proof()
    assert not isinstance(error.value, H.ReadinessPending)


@pytest.mark.parametrize("change", ["fingerprint", "permit", "owner", "invocation"])
def test_pending_completion_does_not_retry_invariant_failure(completion_case, change):
    host, fake, checked, records = completion_case
    now = completion_clock(host)
    calls = []

    def workloads(endpoint):
        calls.append(endpoint)
        raise H.recovery.Stop("workload replicas not Ready")

    fake.workloads = workloads

    def sleep(seconds):
        now[0] += seconds
        if change == "fingerprint":
            records["/target"] = b"changed"
        elif change == "permit":
            records[H.STATE + "/migration-start-consumed.json"] = b"{}"
        elif change == "owner":
            fake.lock = "changed-owner"
        else:
            fake.command = lambda argv: "different-invocation"

    host.completion_sleep = sleep
    with pytest.raises(H.plan.Refused) as error:
        host.verify_completion(host.plan, H.apply_module.CHECKS)
    assert not isinstance(error.value, H.ReadinessPending)
    assert len(calls) == 1
    assert not host.lifecycle_attempts


def test_transient_workload_readiness_converges_without_mutation(completion_case):
    host, fake, checked, records = completion_case
    completion_clock(host)
    calls = []

    def workloads(endpoint):
        calls.append(endpoint)
        if len(calls) < 3:
            raise H.recovery.Stop("workload Pod completion pending")

    fake.workloads = workloads
    host.verify_completion(host.plan, H.apply_module.CHECKS)
    assert len(calls) == 3 and checked.count("config") == 3
    assert not host.lifecycle_attempts


@pytest.mark.parametrize("frozen", [False, True])
def test_completion_wait_is_bounded_even_if_clock_does_not_advance(completion_case, frozen):
    host, fake, checked, records = completion_case
    completion_clock(host)
    if frozen:
        host.completion_sleep = lambda seconds: None
    calls = []

    def workloads(endpoint):
        calls.append(endpoint)
        raise H.recovery.Stop("DaemonSet completion pending")

    fake.workloads = workloads
    with pytest.raises(H.plan.Refused, match="readiness deadline"):
        host.verify_completion(host.plan, H.apply_module.CHECKS)
    assert len(calls) == (H.COMPLETION_ATTEMPTS if frozen else H.COMPLETION_BUDGET // 2)
    assert not host.lifecycle_attempts


@pytest.mark.parametrize(
    "failure",
    [H.recovery.Stop("authenticated RPC failed"), RuntimeError("workload replicas not Ready")],
)
def test_completion_does_not_retry_unclassified_errors(completion_case, failure):
    host, fake, checked, records = completion_case
    host.completion_sleep = lambda seconds: pytest.fail("must not retry")

    def workloads(endpoint):
        raise failure

    fake.workloads = workloads
    with pytest.raises(type(failure)):
        host.verify_completion(host.plan, H.apply_module.CHECKS)
    assert checked.count("config") == 1


def test_slow_successful_completion_still_has_overall_deadline(completion_case):
    host, fake, checked, records = completion_case
    times = iter([0, 0, H.COMPLETION_BUDGET + 1])
    host.completion_clock = lambda: next(times)
    with pytest.raises(H.plan.Refused, match="verification deadline"):
        host.verify_completion(host.plan, H.apply_module.CHECKS)


@pytest.mark.parametrize("phase", ["Pending", "Running"])
def test_probe_pod_pending_is_classified_before_exec(files, phase):
    host, fake = adapter(fixtures.sample(), files)
    calls = []

    def command(argv):
        calls.append(argv)
        return H.json.dumps(
            {
                "metadata": {"uid": "uid"},
                "spec": {"nodeName": "pi1", "containers": [{"name": "main"}]},
                "status": {"phase": phase, "conditions": []},
            }
        )

    fake.command = command
    with pytest.raises(H.ReadinessPending, match="probe pod"):
        host.pod_dns()
    assert len(calls) == 1 and "exec" not in calls[0]


@pytest.mark.parametrize("advance", [H.COMPLETION_BUDGET + 1, -1])
def test_completion_oversleep_or_clock_anomaly_forbids_new_proof(completion_case, advance):
    host, fake, checked, records = completion_case
    now = completion_clock(host)
    calls = []

    def workloads(endpoint):
        calls.append(endpoint)
        raise H.recovery.Stop("workload replicas not Ready")

    fake.workloads = workloads
    host.completion_sleep = lambda seconds: now.__setitem__(0, now[0] + advance)
    with pytest.raises(H.plan.Refused, match="readiness deadline"):
        host.verify_completion(host.plan, H.apply_module.CHECKS)
    assert len(calls) == checked.count("config") == 1


def test_lifecycle_clock_going_backwards_refuses_before_mutation(files):
    host, _ = adapter(fixtures.sample(), files)
    host.lifecycle_started = 100
    host.lifecycle_clock = lambda: 99
    with pytest.raises(H.plan.Refused, match="total budget"):
        host.command("start", "k3s.service")
    assert not host.lifecycle_attempts
