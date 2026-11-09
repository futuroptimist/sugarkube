"""Temporary files and fake authenticated backend only; no systemd invocation."""

import copy
import json

import pytest
from test_ethernet_quorum_recover import MODULE as M


def checked_invocation():
    value = M.os.environ.get("INVOCATION_ID", "")
    M.require(len(value) == 32, "migration requires a systemd invocation")
    return value


class Backend:
    def __init__(self, enrollment, lock_value):
        self.e = enrollment
        self.lock_value = lock_value
        self.calls = []
        self.ip = enrollment["local_ipv4"]

    def address(self):
        return self.ip

    def etcd(self, host, verb, key):
        assert verb == "get" and key == M.KEY
        return {"kvs": [{"value": M.encode(self.lock_value)}]}

    def config(self):
        self.calls.append("config")

    def network(self, ip):
        self.calls.append("network")


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "trusted_file", lambda p: p.lstat())
    monkeypatch.setenv("INVOCATION_ID", "a" * 32)
    monkeypatch.setattr(M, "migration_service_context", lambda b, p: checked_invocation())
    e = {
        "schema_version": 2,
        "armed": True,
        "cluster_id": "1",
        "local_member_id": "2",
        "local_ipv4": "192.0.2.1",
        "members": [{"id": "2", "hostname": "one.local"}, {"id": "3", "hostname": "two.local"}],
    }
    enrollment = tmp_path / "enrollment.json"
    enrollment.write_text(json.dumps(e, sort_keys=True, separators=(",", ":")))
    incident = tmp_path / "incident.json"
    incident.write_text(json.dumps({"phase": "complete", "kind": "enrollment"}))
    owner = {"operation_id": "a" * 64, "plan_sha256": "b" * 64}
    permit = {
        "schema_version": 1,
        "owner": owner,
        "target_enrollment_sha256": M.digest(enrollment.read_bytes()),
        "incident_sha256": M.digest(incident.read_bytes()),
        "baseline_ipv4": e["local_ipv4"],
    }
    intent = {
        **permit,
        "cluster_id": e["cluster_id"],
        "local_member_id": e["local_member_id"],
        "plan_sha256": owner["plan_sha256"],
    }
    (tmp_path / "migration-intent.json").write_text(json.dumps(intent))
    (tmp_path / "migration-start-permit.json").write_text(json.dumps(permit))
    backend = Backend(e, json.dumps(owner, sort_keys=True, separators=(",", ":")))
    return enrollment, backend, tmp_path, permit


def run(case, phase="pre-start"):
    return M.migration_start_guard(*case[:3], phase)


def test_single_start_then_same_invocation_post_start(case):
    before = (case[2] / "incident.json").read_bytes()
    assert run(case) == "migration-start-authorized"
    assert case[1].calls == ["config", "network"]
    assert run(case, "post-start") == "migration-start-observed"
    assert (case[2] / "incident.json").read_bytes() == before
    with pytest.raises(FileExistsError):
        run(case)


@pytest.mark.parametrize("phase", ["watch", "resume", "resume-node-address", "arm", "enroll-peer"])
def test_other_actions_blocked(case, phase):
    with pytest.raises(M.Stop, match="blocks recovery"):
        run(case, phase)
    assert not case[1].calls


@pytest.mark.parametrize(
    "change", ["address", "enrollment", "journal", "node-intent", "owner", "permit"]
)
def test_changed_baseline_refuses_without_consumption(case, change):
    path, backend, state, permit = case
    if change == "address":
        backend.ip = "192.0.2.20"
    elif change == "enrollment":
        path.write_text("{}")
    elif change == "journal":
        (state / "incident.json").write_text("{}")
    elif change == "node-intent":
        (state / "node-address.json").write_text("{}")
    elif change == "owner":
        backend.lock_value = "other"
    else:
        bad = copy.deepcopy(permit)
        bad["owner"]["operation_id"] = "f" * 64
        (state / "migration-start-permit.json").write_text(json.dumps(bad))
    with pytest.raises(M.Stop):
        run(case)
    assert not (state / "migration-start-consumed.json").exists()


def test_different_systemd_invocation_cannot_reuse_post_start(case, monkeypatch):
    run(case)
    monkeypatch.setenv("INVOCATION_ID", "f" * 32)
    with pytest.raises(M.Stop, match="invocation mismatch"):
        run(case, "post-start")


def test_no_systemd_invocation_refused(case, monkeypatch):
    monkeypatch.delenv("INVOCATION_ID")
    with pytest.raises(M.Stop, match="systemd invocation"):
        run(case)


def test_complete_record_releases_guard_without_removing_history(case):
    (case[2] / "migration-complete.json").write_text(json.dumps(case[3]))
    assert run(case, "watch") is None
    assert (case[2] / "migration-intent.json").exists()


def test_bad_complete_does_not_release_guard(case):
    (case[2] / "migration-complete.json").write_text("{}")
    with pytest.raises(M.Stop, match="completion mismatch"):
        run(case, "watch")


def test_no_intent_keeps_existing_behavior(case):
    # Use a new empty directory rather than remove safety history.
    empty = case[2] / "empty"
    empty.mkdir()
    assert M.migration_start_guard(case[0], case[1], empty, "watch") is None


@pytest.mark.parametrize("problem", [None, "invocation", "state", "group", "process"])
def test_real_service_context_checks_all_bindings(monkeypatch, problem):
    monkeypatch.setenv("INVOCATION_ID", "a" * 32)
    values = {
        "InvocationID": "a" * 32,
        "SubState": "start-pre",
        "ControlGroup": "/system.slice/k3s.service",
    }
    if problem == "invocation":
        values["InvocationID"] = "b" * 32
    if problem == "state":
        values["SubState"] = "running"
    if problem == "group":
        values["ControlGroup"] = "/other.service"

    class Service:
        def command(self, argv):
            return "\n".join(f"{key}={value}" for key, value in values.items())

    monkeypatch.setattr(
        M.Path,
        "read_text",
        lambda self: (
            "0::/other.service\n" if problem == "process" else "0::/system.slice/k3s.service\n"
        ),
    )
    if problem:
        with pytest.raises(M.Stop):
            M.migration_service_context(Service(), "pre-start")
    else:
        assert M.migration_service_context(Service(), "pre-start") == "a" * 32


@pytest.mark.parametrize("phase", ["pre-start", "watch", "enroll", "prepare-resolver"])
def test_main_routes_through_guard_before_controller_action(case, monkeypatch, phase):
    backend = case[1]
    backend.close = lambda: None
    monkeypatch.setattr(M, "Backend", lambda e: backend)
    monkeypatch.setattr(M.os, "geteuid", lambda: 0)
    monkeypatch.setattr(M, "private_state", lambda p: p.lstat())
    monkeypatch.setattr(M, "report_startup_failure", lambda b, p: None)
    monkeypatch.setattr(M, "enroll", lambda *args: pytest.fail("enrollment bypass"))
    monkeypatch.setattr(M, "prepare_resolver", lambda *args: pytest.fail("resolver bypass"))
    monkeypatch.setattr(M, "Recovery", lambda *args: pytest.fail("controller bypass"))
    monkeypatch.setattr(M, "DualRecovery", lambda *args: pytest.fail("controller bypass"))
    monkeypatch.setattr(
        "sys.argv", ["controller", phase, "--enrollment", str(case[0]), "--state-dir", str(case[2])]
    )
    assert M.main() == (0 if phase == "pre-start" else 2)


@pytest.mark.parametrize("phase", ["watch", "pre-start", "resume"])
def test_completed_migration_allows_arm_json_reformatting(case, monkeypatch, phase):
    from types import SimpleNamespace

    path, backend, state, permit = case
    (state / "migration-complete.json").write_text(json.dumps(permit))
    original = path.read_bytes()
    backend.close = lambda: None
    monkeypatch.setattr(M, "Backend", lambda e: backend)
    monkeypatch.setattr(M.os, "geteuid", lambda: 0)
    monkeypatch.setattr(M, "private_state", lambda p: p.lstat())
    actions = {
        name: (lambda: "unchanged")
        for name in (
            "pre_start",
            "post_start",
            "watch",
            "resume",
            "enroll_peer",
            "resume_transport",
            "resume_node_address",
        )
    }
    actions["arm"] = lambda: "armed"
    monkeypatch.setattr(M, "DualRecovery", lambda *args: SimpleNamespace(**actions))
    monkeypatch.setattr(
        "sys.argv", ["controller", "arm", "--enrollment", str(path), "--state-dir", str(state)]
    )
    assert M.main() == 0
    assert path.read_bytes() != original
    assert json.loads(path.read_bytes()) == json.loads(original)
    assert run(case, phase) is None


@pytest.mark.parametrize("change", ["armed", "address", "unknown", "type"])
def test_completed_guard_still_rejects_enrollment_content_change(case, change):
    path, backend, state, permit = case
    (state / "migration-complete.json").write_text(json.dumps(permit))
    e = json.loads(path.read_bytes())
    if change == "armed":
        e["armed"] = False
    elif change == "address":
        e["local_ipv4"] = "192.0.2.9"
    elif change == "unknown":
        e["unexpected"] = "field"
    else:
        e["schema_version"] = 2.0
    path.write_text(json.dumps(e, indent=2))
    with pytest.raises(M.Stop, match="completed migration enrollment changed"):
        run(case, "watch")


@pytest.mark.parametrize(
    "raw,diagnostic",
    [
        ('{"armed":true,"armed":true}', "duplicate"),
        ('{"unexpected":NaN}', "nonfinite"),
        ('{"unexpected":1e999}', "nonfinite"),
        ('{"unexpected":-1e999}', "nonfinite"),
        ("[]", "invalid migration record"),
    ],
)
def test_completed_guard_refuses_ambiguous_json(case, raw, diagnostic):
    (case[2] / "migration-complete.json").write_text(json.dumps(case[3]))
    case[0].write_text(raw)
    with pytest.raises(M.Stop, match=diagnostic):
        run(case, "watch")


def test_active_migration_still_binds_exact_enrollment_bytes(case):
    M.atomic_json(case[0], json.loads(case[0].read_bytes()))
    with pytest.raises(M.Stop, match="migration baseline changed"):
        run(case)


@pytest.mark.parametrize("artifact", ["intent", "complete", "enrollment"])
@pytest.mark.parametrize("raw", [b"{", b"\xff"])
def test_malformed_record_is_always_a_guard_stop(case, artifact, raw):
    path, _, state, permit = case
    if artifact == "intent":
        target = state / "migration-intent.json"
    else:
        (state / "migration-complete.json").write_text(json.dumps(permit))
        target = state / "migration-complete.json" if artifact == "complete" else path
    target.write_bytes(raw)
    with pytest.raises(M.Stop, match="invalid migration record JSON"):
        run(case, "watch")


def test_guard_parser_recursion_failure_is_normalized(case, monkeypatch):
    def exhausted(*args, **kwargs):
        raise RecursionError("decoder nesting limit")

    monkeypatch.setattr(M.json, "loads", exhausted)
    with pytest.raises(M.Stop, match="invalid migration record JSON"):
        run(case, "watch")


@pytest.mark.parametrize("replacement", ["symlink", "regular", "fifo"])
def test_record_swap_before_open_refuses(case, monkeypatch, replacement):
    path = case[2] / "migration-intent.json"
    original = path.read_bytes()
    saved = path.with_suffix(".saved")
    real_open = M.os.open
    flags_seen = []

    def swapped_open(target, flags, *args):
        if target == path:
            flags_seen.append(flags)
            path.rename(saved)
            if replacement == "symlink":
                path.symlink_to(saved)
            elif replacement == "regular":
                path.write_bytes(original)
            else:
                M.os.mkfifo(path)
        return real_open(target, flags, *args)

    monkeypatch.setattr(M.os, "open", swapped_open)
    with pytest.raises(M.Stop, match="trusted migration record|changed during open"):
        run(case)
    assert len(flags_seen) == 1
    assert flags_seen[0] & M.os.O_NOFOLLOW
    assert flags_seen[0] & M.os.O_NONBLOCK
    assert saved.read_bytes() == original
    assert not (case[2] / "migration-start-consumed.json").exists()


@pytest.mark.parametrize("drift", ["grow", "truncate", "same-size", "replace", "symlink", "mode"])
def test_record_drift_during_read_refuses(case, monkeypatch, drift):
    path = case[2] / "record"
    path.write_bytes(b"1234")
    real_fdopen = M.os.fdopen
    sizes = []

    class Reader:
        def __init__(self, fd, mode):
            self.handle = real_fdopen(fd, mode)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def fileno(self):
            return self.handle.fileno()

        def read(self, size):
            sizes.append(size)
            if drift == "grow":
                path.write_bytes(b"x" * 20)
            elif drift == "truncate":
                path.write_bytes(b"1")
            elif drift == "same-size":
                path.write_bytes(b"4321")
            elif drift == "mode":
                path.chmod(0o666)
            else:
                saved = path.with_suffix(".saved")
                path.rename(saved)
                if drift == "replace":
                    path.write_bytes(b"1234")
                else:
                    path.symlink_to(saved)
            return self.handle.read(size)

    monkeypatch.setattr(M.os, "fdopen", Reader)
    with pytest.raises(M.Stop, match="too large|changed during read"):
        M.migration_record_bytes(path, 8)
    assert sizes == [9]


@pytest.mark.parametrize("kind", ["oversized", "symlink", "hardlink", "directory"])
def test_record_invalid_initial_file_never_opened(case, monkeypatch, kind):
    path = case[2] / "record"
    if kind == "directory":
        path.mkdir()
    elif kind == "symlink":
        path.symlink_to(case[0])
    else:
        path.write_bytes(b"x" * (9 if kind == "oversized" else 4))
        if kind == "hardlink":
            M.os.link(path, path.with_suffix(".link"))
    monkeypatch.setattr(M.os, "open", lambda *a: pytest.fail("must refuse before open"))
    with pytest.raises(M.Stop, match="too large|single-link regular"):
        M.migration_record_bytes(path, 8)


def test_record_exact_size_ceiling(case):
    path = case[2] / "record"
    path.write_bytes(b"12345678")
    assert M.migration_record_bytes(path, 8) == b"12345678"


def test_original_incident_retains_eight_megabyte_allowance(case):
    incident = case[2] / "incident.json"
    incident.write_bytes(b" " * 65536 + incident.read_bytes())
    for name in ("migration-intent.json", "migration-start-permit.json"):
        path = case[2] / name
        value = json.loads(path.read_bytes())
        value["incident_sha256"] = M.digest(incident.read_bytes())
        path.write_text(json.dumps(value))
    assert run(case) == "migration-start-authorized"
