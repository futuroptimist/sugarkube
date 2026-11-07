"""Offline orchestration tests. Fake backends are not live qualification."""

import copy
import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
import test_ethernet_migration_plan as fixtures

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "migration_apply", ROOT / "scripts/ethernet_migration_apply.py"
)
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)
P = A.planner


class FakeBackend:
    def __init__(self, bundle, store):
        self.bundle = bundle
        self.store = store
        self.calls = []
        self.failure = None
        self.drift = False
        self.writes = {}

    def event(self, name):
        self.calls.append(name)
        if name == self.failure:
            raise RuntimeError("simulated uncertain outcome")

    @contextmanager
    def exclusive_local_lock(self):
        self.event("lock")
        yield
        self.event("unlock")

    def capture(self, nonce):
        self.event("capture")
        fresh = copy.deepcopy(self.bundle)
        for container in (fresh, fresh["health"], fresh["backup"]):
            container["capture_id"] = nonce
        if self.drift:
            fresh["backup"]["snapshot_sha256"] = "b" * 64
        return fresh

    def check_gates(self, gates):
        assert gates == A.GATES
        self.event("gates")

    def acquire_cluster_lock(self, commitment):
        assert (self.store.directory / "migration-intent.json").exists()
        self.event("cluster-lock")

    def reprove_under_lock(self, bundle, commitment):
        self.event("reprove")

    def release_cluster_lock(self, commitment):
        self.event("release")

    def stop_local_services(self):
        assert (self.store.directory / "migration-intent.json").exists()
        self.event("stop")

    def verify_stopped_and_preserved(self, bundle):
        assert bundle == self.bundle
        self.event("stopped")

    def replace_file(self, path, old_digest, data):
        # The fake models CAS and records bytes, never touches host paths.
        expected = (
            P.sha(self.bundle["enrollment_json"].encode())
            if path == A.ENROLLMENT
            else self.bundle["observed"][path]["sha256"]
        )
        assert expected == old_digest
        self.writes[path] = data
        self.event("write:" + path)

    def activate_local_services(self):
        self.event("activate")

    def verify_completion(self, plan, checks):
        assert checks == A.CHECKS
        self.event("completion")

    def resume_timer(self):
        self.event("resume")

    def verify_timer_and_completion(self, plan, checks):
        assert checks == A.CHECKS
        self.event("final")


@pytest.fixture
def case(tmp_path, monkeypatch):
    # Use a synthetic pinned catalog so no historical runtime binaries need to
    # be installed or fetched. Production still uses the immutable real pin.
    catalog = P.parse(A.CATALOG.read_bytes())
    runtime = {
        path: ("fake:" + path).encode() for path in catalog["artifacts"]["target"]["runtime_sha256"]
    }
    catalog["artifacts"]["target"]["runtime_sha256"] = {p: P.sha(v) for p, v in runtime.items()}
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_bytes(P.canonical(catalog))
    for module in (P, fixtures.M):
        monkeypatch.setattr(module, "CATALOG", catalog_path)
        monkeypatch.setattr(module, "CATALOG_SHA256", P.sha(catalog_path.read_bytes()))
    monkeypatch.setattr(A, "CATALOG", catalog_path)
    monkeypatch.setattr(A, "CATALOG_SHA256", P.sha(catalog_path.read_bytes()))
    bundle = fixtures.sample()
    plan = A.guarded_plan(bundle)
    approval = {
        "plan_sha256": P.sha(P.canonical(plan)),
        "expires_at": 120,
        "gates": {g: True for g in A.GATES},
    }
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    store = A.IntentStore(state)
    backend = FakeBackend(bundle, store)
    return bundle, plan, approval, runtime, backend, store


def run(case, clock=lambda: 100):
    return A.apply(*case, clock=clock)


def test_success_preserves_identity_and_commits_enrollment_last(case):
    before = copy.deepcopy(case[:4])
    result = run(case)
    bundle, plan, _, _, backend, store = case
    assert result["completed"] and not result["replay_allowed"]
    assert case[:4] == before
    new = P.parse(backend.writes[A.ENROLLMENT])
    old = P.parse(bundle["enrollment_json"])
    for key in old.keys() - {"files"}:
        assert new[key] == old[key]
    assert set(backend.writes) == {t["path"] for t in plan["transitions"]} | {A.ENROLLMENT}
    assert list(backend.writes)[0] == A.CONTROLLER
    assert list(backend.writes)[-1] == A.ENROLLMENT
    assert backend.calls[-6:] == ["activate", "completion", "release", "resume", "final", "unlock"]
    record = P.parse((store.directory / "migration-intent.json").read_bytes())
    assert record["phase"] == "intent"
    assert "enrollment_json" not in record


@pytest.mark.parametrize("mutation", ["plan", "approval", "expiry", "gate", "runtime", "capture"])
def test_reject_before_side_effects(case, mutation):
    bundle, plan, approval, runtime, backend, store = case
    if mutation == "plan":
        plan["authorized_to_execute"] = True
    elif mutation == "approval":
        approval["plan_sha256"] = "0" * 64
    elif mutation == "expiry":
        approval["expires_at"] = 99
    elif mutation == "gate":
        approval["gates"]["one_server_window"] = False
    elif mutation == "runtime":
        runtime[next(iter(runtime))] = b"unapproved"
    else:
        backend.drift = True
    with pytest.raises(P.Refused):
        run(case)
    assert not backend.writes
    assert "stop" not in backend.calls
    assert not (store.directory / "migration-intent.json").exists()


@pytest.mark.parametrize(
    "failure", ["stop", "stopped", "activate", "completion", "resume", "final", "write"]
)
def test_uncertain_outcome_never_replayed(case, failure):
    backend = case[4]
    backend.failure = (
        "write:" + case[1]["transitions"][0]["path"] if failure == "write" else failure
    )
    with pytest.raises(RuntimeError):
        run(case)
    prior_stops = backend.calls.count("stop")
    backend.failure = None
    with pytest.raises(P.Refused, match="reconciliation"):
        run(case)
    assert backend.calls.count("stop") == prior_stops == 1
    if failure in ("stop", "stopped", "write", "activate", "completion"):
        assert "resume" not in backend.calls


def test_completed_run_also_cannot_replay(case):
    run(case)
    with pytest.raises(P.Refused, match="reconciliation"):
        run(case)
    assert case[4].calls.count("stop") == 1


def test_slow_capture_refused(case):
    ticks = iter([100, 100, 131])
    with pytest.raises(P.Refused, match="expired"):
        run(case, lambda: next(ticks))
    assert "stop" not in case[4].calls


def test_intent_sync_failure_prevents_stop(case, monkeypatch):
    def fail(_):
        raise OSError("simulated fsync error")

    monkeypatch.setattr(A.os, "fsync", fail)
    with pytest.raises(OSError):
        run(case)
    assert "stop" not in case[4].calls
    assert (case[5].directory / "migration-intent.json").exists()


def test_existing_truncated_intent_is_not_replaced(case):
    path = case[5].directory / "migration-intent.json"
    path.write_bytes(b"{")
    with pytest.raises(P.Refused, match="reconciliation"):
        run(case)
    assert path.read_bytes() == b"{"
    assert "stop" not in case[4].calls


def test_symlink_intent_cannot_clobber_target(case, tmp_path):
    target = tmp_path / "preserved"
    target.write_text("unchanged")
    (case[5].directory / "migration-intent.json").symlink_to(target)
    with pytest.raises(P.Refused):
        run(case)
    assert target.read_text() == "unchanged"


def test_world_writable_state_directory_refused(case):
    case[5].directory.chmod(0o777)
    with pytest.raises(P.Refused, match="untrusted"):
        run(case)
    assert "stop" not in case[4].calls


@pytest.mark.parametrize("failure", ["cluster-lock", "reprove", "release"])
def test_cluster_cas_uncertainty_is_latched(case, failure):
    backend = case[4]
    backend.failure = failure
    with pytest.raises(RuntimeError):
        run(case)
    stops = backend.calls.count("stop")
    backend.failure = None
    with pytest.raises(P.Refused, match="reconciliation"):
        run(case)
    assert backend.calls.count("stop") == stops
    assert "resume" not in backend.calls


def test_phase_intents_and_random_owner_are_persisted(case):
    run(case)
    state = case[5].directory
    intent = P.parse((state / "migration-intent.json").read_bytes())
    events = [P.parse(path.read_bytes()) for path in sorted(state.glob("migration-event-*.json"))]
    owner = intent["owner"]
    assert len(owner["operation_id"]) == 64
    assert owner["operation_id"] != owner["plan_sha256"]
    assert events[0] == {"phase": "acquire-intent", "owner": owner}
    assert events[-1] == {"phase": "complete"}
    assert next(e for e in events if e["phase"] == "release-intent")["owner"] == owner
    assert [e["path"] for e in events if e["phase"] == "replace-intent"] == [
        t["path"]
        for t in sorted(
            case[1]["transitions"], key=lambda t: (t["path"] != A.CONTROLLER, t["path"])
        )
    ]


def test_non_boolean_gate_refused(case):
    case[2]["gates"]["one_server_window"] = 1
    with pytest.raises(P.Refused, match="gates"):
        run(case)
    assert "stop" not in case[4].calls


def test_real_guarded_catalog_pins_current_guard_and_preserves_historical_source():
    raw = A.CATALOG.read_bytes()
    assert P.sha(raw) == A.CATALOG_SHA256
    guarded = P.parse(raw)
    historical = P.parse(P.CATALOG.read_bytes())
    assert guarded["artifacts"]["source"] == historical["artifacts"]["source"]
    assert guarded["revisions"]["source"] == historical["revisions"]["source"]
    assert guarded["artifacts"]["target"]["runtime_sha256"][A.CONTROLLER] == P.sha(
        (ROOT / "scripts/ethernet_quorum_recover.py").read_bytes()
    )
    assert guarded["revisions"]["target"] != historical["revisions"]["target"]
    assert A.guarded_plan(fixtures.sample())["authorized_to_execute"] is False


def test_guarded_catalog_tamper_refused(tmp_path, monkeypatch):
    path = tmp_path / "tampered.json"
    path.write_bytes(b"{}")
    monkeypatch.setattr(A, "CATALOG", path)
    with pytest.raises(P.Refused, match="guarded artifact catalog"):
        A.guarded_plan(fixtures.sample())


def test_expiry_during_lock_reproof_latches_without_stopping(case):
    ticks = iter([100, 100, 100, 100, 121])
    with pytest.raises(P.Refused, match="before service stop"):
        run(case, lambda: next(ticks))
    assert "cluster-lock" in case[4].calls
    assert "stop" not in case[4].calls
    assert (case[5].directory / "migration-intent.json").exists()


def test_previous_guarded_catalog_is_preserved_not_rewritten():
    previous_path = A.CATALOG.with_name("resolver-v1-to-guarded-directory-v1.json")
    raw = previous_path.read_bytes()
    assert P.sha(raw) == "d7046d634e3a7f7faeb8557de8c00a42dd2de9894771bf4090d02881845510a8"
    previous = P.parse(raw)
    current = P.parse(A.CATALOG.read_bytes())
    assert previous["revisions"]["target"] == "09653988b32cfc4f866aa98fff90a8f0e12f6abd"
    assert current["revisions"]["target"] == "ebf4748d5d84e61bfbc61493df7f95278cfc68e2"
    assert previous["artifacts"]["source"] == current["artifacts"]["source"]
    assert (
        previous["artifacts"]["target"]["templates"] == current["artifacts"]["target"]["templates"]
    )
    before = dict(previous["artifacts"]["target"]["runtime_sha256"])
    after = dict(current["artifacts"]["target"]["runtime_sha256"])
    assert before.pop(A.CONTROLLER) != after.pop(A.CONTROLLER)
    assert before == after


@pytest.mark.parametrize("expiry", [True, False])
def test_boolean_approval_expiry_is_not_a_timestamp(case, expiry):
    case[2]["expires_at"] = expiry
    with pytest.raises(P.Refused, match="expired or unbounded approval"):
        run(case)
    assert not case[4].calls
