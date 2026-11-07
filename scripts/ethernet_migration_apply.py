#!/usr/bin/env python3
"""Guarded migration orchestration, separate from the explicit host adapter.

Backend implementations are trusted code, not operator-supplied evidence. See
docs/ethernet-migration-apply.md before implementing or invoking a backend.
"""

import copy
import importlib.util
import json
import os
import secrets
import stat
import time
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "sugarkube_migration_plan", Path(__file__).with_name("ethernet_migration_plan.py")
)
planner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(planner)

CATALOG = Path(__file__).with_name("migration") / "resolver-v1-to-guarded-directory-v1.json"
CATALOG_SHA256 = "d7046d634e3a7f7faeb8557de8c00a42dd2de9894771bf4090d02881845510a8"


def guarded_plan(bundle):
    """Read-only plan for the separately pinned migration-aware target."""
    raw = CATALOG.read_bytes()
    planner.require(planner.sha(raw) == CATALOG_SHA256, "unsupported guarded artifact catalog")
    return planner._admit(bundle, planner.parse(raw))


ENROLLMENT = "/etc/rancher/k3s/sugarkube-recovery.json"
CONTROLLER = "/usr/local/libexec/sugarkube/ethernet-quorum-recover.py"
MAX_AGE = 30
GATES = {
    "backup_restore_verified",
    "one_server_window",
    "timer_paused",
    "controller_idle",
    "cluster_migration_lock",
}
CHECKS = {
    "original_quorum",
    "original_node_uids",
    "database_identity",
    "journals_unchanged",
    "unrelated_files_unchanged",
    "loaded_units",
    "real_mount_and_ipc",
    "pod_dns",
    "workload_https",
    "target_artifacts",
    "target_enrollment",
}


class IntentStore:
    """Single-use, durable intent in an existing trusted local state directory.

    Never delete or reuse this record automatically, including after completion.
    The host adapter owns lock acquisition and the guarded startup handoff.
    """

    def __init__(self, directory):
        self.directory = Path(directory)
        self.sequence = 0

    def reserve(self, record):
        self._write("migration-intent.json", record)

    def event(self, phase, **details):
        self.sequence += 1
        self._write(f"migration-event-{self.sequence:04d}.json", {"phase": phase, **details})

    def _write(self, name, record):
        # Directory must already exist. No parent creation, symlink following,
        # truncation, or replacement of a previous intent is allowed.
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            planner.require(
                info.st_uid == os.geteuid() and not stat.S_IMODE(info.st_mode) & 0o022,
                "untrusted migration intent directory",
            )
            try:
                out = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=fd,
                )
            except FileExistsError as exc:
                raise planner.Refused("existing migration intent requires reconciliation") from exc
            with os.fdopen(out, "wb") as handle:
                handle.write(planner.canonical(record) + b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.fsync(fd)
        finally:
            os.close(fd)


def target_payloads(bundle, expected_plan, runtime):
    """Render pinned target bytes only; never accept arbitrary destination paths."""
    catalog_raw = CATALOG.read_bytes()
    planner.require(planner.sha(catalog_raw) == CATALOG_SHA256, "unsupported artifact catalog")
    catalog = planner.parse(catalog_raw)
    enrollment = planner.parse(bundle["enrollment_json"])
    target = catalog["artifacts"]["target"]
    planner.shape(runtime, target["runtime_sha256"], "incomplete target runtime inventory")
    for path, digest in target["runtime_sha256"].items():
        planner.require(type(runtime[path]) is bytes, "target runtime must be bytes")
        planner.require(planner.sha(runtime[path]) == digest, "unpinned target runtime")
    payloads = {**runtime, **{p: value.encode() for p, value in target["templates"].items()}}
    config = {
        "schema_version": 2,
        "interface": enrollment["interface"],
        "pod_resolv_source": enrollment["pod_resolv_source"],
        "members": [{"hostname": m["hostname"]} for m in enrollment["members"]],
        "resolver_view": expected_plan["new_descriptor"],
    }
    payloads[planner.CONFIG] = (json.dumps(config, sort_keys=True) + "\n").encode()
    changes = {}
    for transition in expected_plan["transitions"]:
        path = transition["path"]
        data = payloads[path]
        planner.require(planner.sha(data) == transition["new_sha256"], "target plan mismatch")
        changes[path] = data
    new_enrollment = copy.deepcopy(enrollment)
    new_enrollment["resolver_view"] = expected_plan["new_descriptor"]
    for transition in expected_plan["transitions"]:
        if transition["enrolled_fingerprint"]:
            new_enrollment["files"][transition["path"]] = transition["new_sha256"]
    data = planner.canonical(new_enrollment)
    planner.require(
        planner.sha(data) == expected_plan["new_enrollment_canonical_sha256"],
        "target enrollment commitment mismatch",
    )
    changes[ENROLLMENT] = data
    return changes


def _same_capture(original, fresh, nonce):
    """Allow a new challenge, but no drift in any admitted captured fact."""
    planner.require(fresh["capture_id"] == nonce, "capture challenge mismatch")
    normalized = copy.deepcopy(fresh)
    for container in (normalized, normalized["health"], normalized["backup"]):
        container["capture_id"] = original["capture_id"]
    planner.require(planner.canonical(normalized) == planner.canonical(original), "capture drift")


def apply(bundle, approved_plan, approval, runtime, backend, intent_store, clock=time.monotonic):
    """Run once under a trusted backend's exclusive host and cluster locks.

    This API does not authenticate an operator. The caller is responsible for
    obtaining separate operational approval and constructing the approval record.
    The separate host adapter verifies current facts and private attestations.
    Fabricated records and fake backends are suitable only for offline tests.
    A backend method may have succeeded before raising: every post-intent failure
    therefore requires manual reconciliation, never retry or automatic rollback.
    """
    bundle = copy.deepcopy(bundle)
    approved_plan = copy.deepcopy(approved_plan)
    approval = copy.deepcopy(approval)
    runtime = dict(runtime)
    actual = guarded_plan(bundle)
    planner.require(planner.canonical(actual) == planner.canonical(approved_plan), "plan mismatch")
    commitment = planner.sha(planner.canonical(actual))
    planner.shape(approval, {"plan_sha256", "expires_at", "gates"}, "missing operational approval")
    planner.require(approval["plan_sha256"] == commitment, "approval plan mismatch")
    planner.require(
        type(approval["expires_at"]) in (int, float)
        and 0 < approval["expires_at"] - clock() <= MAX_AGE,
        "expired or unbounded approval",
    )
    planner.require(
        planner.canonical(approval["gates"]) == planner.canonical({key: True for key in GATES}),
        "missing operational gates",
    )
    payloads = target_payloads(bundle, actual, runtime)
    # Local locking is read-only. The cluster CAS follows durable intent; a
    # timeout during acquisition is uncertain and must never be retried blindly.
    with backend.exclusive_local_lock():
        nonce = secrets.token_hex(32)
        started = clock()
        fresh = backend.capture(nonce)
        guarded_plan(fresh)
        _same_capture(bundle, fresh, nonce)
        planner.require(
            0 <= clock() - started <= MAX_AGE and clock() < approval["expires_at"],
            "fresh proof or approval expired",
        )
        backend.check_gates(frozenset(GATES))
        # Durable intent PRECEDES stop, installation, activation and timer resume.
        # A partial write/fsync error also leaves a blocking intent where possible.
        owner = {"operation_id": secrets.token_hex(32), "plan_sha256": commitment}
        intent_store.reserve(
            {
                "schema_version": 1,
                "phase": "intent",
                "owner": owner,
                "plan_sha256": commitment,
                "capture_sha256": planner.sha(planner.canonical(fresh)),
                "cluster_id": actual["cluster_id"],
                "local_member_id": actual["local_member_id"],
                "target_enrollment_sha256": actual["new_enrollment_canonical_sha256"],
                "incident_sha256": planner.sha(bundle["journals"]["incident_json"].encode()),
                "baseline_ipv4": planner.parse(bundle["enrollment_json"])["local_ipv4"],
            }
        )
        intent_store.event("acquire-intent", owner=owner)
        backend.acquire_cluster_lock(owner)
        backend.reprove_under_lock(bundle, owner)
        planner.require(clock() < approval["expires_at"], "approval expired before service stop")
        intent_store.event("stop-intent")
        backend.stop_local_services()
        backend.verify_stopped_and_preserved(bundle)
        transitions = sorted(
            actual["transitions"], key=lambda t: (t["path"] != CONTROLLER, t["path"])
        )
        for transition in transitions:
            intent_store.event("replace-intent", **transition)
            backend.replace_file(
                transition["path"], transition["old_sha256"], payloads[transition["path"]]
            )
        # Commit enrollment last. Its identities, journal references, backup and
        # unrelated fingerprints are preserved by construction, not regenerated.
        intent_store.event("enrollment-intent", sha256=planner.sha(payloads[ENROLLMENT]))
        backend.replace_file(ENROLLMENT, actual["old_enrollment_sha256"], payloads[ENROLLMENT])
        intent_store.event("activation-intent")
        backend.activate_local_services()
        backend.verify_completion(actual, frozenset(CHECKS))
        intent_store.event("release-intent", owner=owner)
        backend.release_cluster_lock(owner)
        intent_store.event("timer-resume-intent")
        backend.resume_timer()
        backend.verify_timer_and_completion(actual, frozenset(CHECKS))
        intent_store.event("complete")
    return {"completed": True, "plan_sha256": commitment, "replay_allowed": False}
