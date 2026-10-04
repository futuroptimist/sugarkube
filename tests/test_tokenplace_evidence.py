"""Privacy, storage and retention contracts for offline incident aggregates."""

import fcntl
import importlib.util
import io
import itertools
import json
import os
import runpy
import stat
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/tokenplace_evidence.py"
SPEC = importlib.util.spec_from_file_location("evidence", SCRIPT)
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)
BUCKET = 1800000000
NOW = BUCKET + 300


def bucket(environment="staging", timestamp=BUCKET):
    return {
        "schema_version": 1,
        "environment": environment,
        "bucket": timestamp,
        "coverage": {key: "complete" for key in ("http", "quota", "scrape", "runtime")},
        "http": [["GET", "2xx", 100], ["POST", "4xx", 2]],
        "quota": [
            ["root", "GET", "exempt", "none", 100],
            ["unmatched", "POST", "rejected", "hourly_limit", 2],
        ],
        "scrape": {key: 1 for key in evidence.SCRAPE},
        "runtime": {"restarts": 0, "ooms": 0},
    }


def append(store, record=None, now=NOW):
    return evidence.operate(store, "append", evidence.encode(record or bucket()), now=now)


def test_round_trip_preserves_trends_and_idempotent_reordered_replay(tmp_path):
    store = tmp_path / "store"
    first = bucket()
    second = bucket(timestamp=BUCKET + 300)
    second["http"][0][-1] = 20
    second["quota"][1][-1] = 3.25  # Prometheus increase may be extrapolated.
    second["runtime"] = {"restarts": 1, "ooms": 1}
    second["scrape"]["route_series_max"] = 5
    append(store, first)
    append(store, second, NOW + 300)
    first["http"].reverse()
    append(store, first, NOW + 300)
    result = [
        json.loads(line) for line in evidence.operate(store, "export", now=NOW + 300).splitlines()
    ]
    assert result == [evidence.validate(first, NOW), evidence.validate(second, NOW + 300)]
    assert stat.S_IMODE(store.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in store.iterdir())


def test_expiry_boundary_prunes_both_export_and_disk(tmp_path):
    store = tmp_path / "store"
    append(store)
    assert evidence.operate(store, "export", now=BUCKET + 86400 - 1)
    assert evidence.operate(store, "export", now=BUCKET + 86400) == b""
    assert list(store.iterdir()) == [store / ".lock"]
    with pytest.raises(evidence.EvidenceError, match="expired input"):
        append(store, now=BUCKET + 86400)
    assert evidence.operate(store, "prune", now=BUCKET + 86400) == b""


def test_ring_reuses_expired_slot_and_environments_are_independent(tmp_path):
    store = tmp_path / "store"
    append(store)
    append(store, bucket("prod"))
    future = bucket(timestamp=BUCKET + 86400)
    assert evidence.filename(future) == evidence.filename(bucket())
    append(store, future, NOW + 86400)
    records = [
        json.loads(line) for line in evidence.operate(store, "export", now=NOW + 86400).splitlines()
    ]
    assert records == [evidence.validate(future, NOW + 86400)]


def test_conflicting_replay_does_not_replace_valid_bucket(tmp_path):
    store = tmp_path / "store"
    append(store)
    before = evidence.operate(store, "export", now=NOW)
    changed = bucket()
    changed["runtime"]["restarts"] = 1
    with pytest.raises(evidence.EvidenceError, match="conflicting"):
        append(store, changed)
    assert evidence.operate(store, "export", now=NOW) == before


def test_all_valid_label_combinations_fit_serialized_bound():
    record = bucket()
    record["http"] = [
        [*labels, evidence.MAX_VALUE]
        for labels in itertools.product(evidence.METHODS, evidence.STATUSES)
    ]
    record["quota"] = [
        [*labels, evidence.MAX_VALUE]
        for labels in itertools.product(
            evidence.ROUTES, evidence.METHODS, evidence.OUTCOMES, evidence.REASONS
        )
        if (labels[2] == "rejected") != (labels[3] == "none")
    ]
    validated = evidence.validate(record, NOW)
    assert len(validated["http"]) == 48
    assert len(validated["quota"]) == 480
    assert len(evidence.encode(validated)) < evidence.MAX_BYTES
    assert len(evidence.FILES) == 576


def test_full_store_has_fixed_keys_and_prunes_expired_slots(tmp_path):
    store = tmp_path / "store"
    store.mkdir(mode=0o700)
    for environment in evidence.ENVIRONMENTS:
        for slot in range(evidence.SLOTS):
            record = bucket(environment, BUCKET + slot * 300)
            path = store / evidence.filename(record)
            path.write_bytes(evidence.encode(record))
            path.chmod(0o600)
    end = BUCKET + evidence.RETENTION_SECONDS
    output = evidence.operate(store, "export", now=end)
    assert len(output.splitlines()) == 574
    assert len(list(store.iterdir())) == 575  # 574 live records and the empty lock.
    assert sum(path.stat().st_size for path in store.iterdir()) <= 576 * evidence.MAX_BYTES
    assert evidence.operate(store, "export", now=end + evidence.RETENTION_SECONDS) == b""
    assert list(store.iterdir()) == [store / ".lock"]


def test_thousands_of_unmatched_identities_cannot_create_labels_or_files(tmp_path):
    store = tmp_path / "store"
    for index in range(1024):
        record = bucket()
        record["quota"][0][0] = f"private-sensitive-{index}"
        with pytest.raises(evidence.EvidenceError, match="^invalid label$"):
            append(store, record)
    assert not store.exists()
    append(store)
    output = evidence.operate(store, "export", now=NOW)
    assert b"private-sensitive" not in output
    assert len(list(store.iterdir())) == 2


@pytest.mark.parametrize(
    "key",
    [
        "path",
        "query",
        "request_id",
        "source_address",
        "user_agent",
        "credential",
        "ciphertext",
        "prompt",
        "response",
        "error",
    ],
)
def test_forbidden_fields_rejected_before_store_creation(tmp_path, key):
    record = bucket()
    record[key] = "private-sensitive-value"
    store = tmp_path / "store"
    with pytest.raises(evidence.EvidenceError, match="^invalid fields$"):
        append(store, record)
    assert not store.exists()


@pytest.mark.parametrize(
    "value", [-1, float("inf"), float("nan"), True, "private", None, 10**12 + 1]
)
def test_invalid_aggregates(value):
    record = bucket()
    record["http"][0][-1] = value
    with pytest.raises(evidence.EvidenceError, match="invalid aggregate"):
        evidence.validate(record, NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("environment", "private"),
        ("bucket", True),
        ("bucket", -300),
        ("bucket", BUCKET + 1),
        ("bucket", 2**54),
        ("bucket", NOW),
        ("coverage", {}),
        ("runtime", {}),
        ("http", {}),
        ("http", [["GET"]]),
        ("http", [[{}, "2xx", 1]]),
        ("http", [["CUSTOM", "2xx", 1]]),
        ("http", [["GET", "private", 1]]),
        ("http", [["GET", "2xx", 1]] * 49),
        ("quota", [["unmatched", "GET", "rejected", "none", 1]]),
        ("quota", [["root", "GET", "accepted", "hourly_limit", 1]]),
    ],
)
def test_invalid_schema(field, value):
    record = bucket()
    record[field] = value
    with pytest.raises(evidence.EvidenceError):
        evidence.validate(record, NOW)


def test_duplicate_rows_and_unknown_coverage():
    record = bucket()
    record["http"].append(record["http"][0])
    with pytest.raises(evidence.EvidenceError, match="duplicate row"):
        evidence.validate(record, NOW)
    record = bucket()
    record["coverage"]["http"] = "private"
    with pytest.raises(evidence.EvidenceError, match="invalid coverage"):
        evidence.validate(record, NOW)


def test_missing_data_is_not_zero():
    record = bucket()
    for field in record["coverage"]:
        record["coverage"][field] = "unavailable"
    with pytest.raises(evidence.EvidenceError, match="empty"):
        evidence.validate(record, NOW)
    record["http"], record["quota"] = [], []
    with pytest.raises(evidence.EvidenceError, match="null"):
        evidence.validate(record, NOW)
    record["scrape"] = dict.fromkeys(evidence.SCRAPE)
    record["runtime"] = dict.fromkeys(evidence.RUNTIME)
    assert evidence.validate(record, NOW) == record
    record["coverage"] = dict.fromkeys(record["coverage"], "partial")
    assert evidence.validate(record, NOW) == record
    record["coverage"]["runtime"] = "complete"
    with pytest.raises(evidence.EvidenceError, match="invalid aggregate"):
        evidence.validate(record, NOW)


@pytest.mark.parametrize(
    "raw", [b"{", b"\xff", b'{"x":1,"x":2}', b"[" * 2000, b" " * (evidence.MAX_BYTES + 1)]
)
def test_bad_json_and_input_size(raw):
    with pytest.raises(evidence.EvidenceError):
        evidence.decode(raw)


def test_serialized_size_is_checked(monkeypatch):
    monkeypatch.setattr(evidence, "MAX_BYTES", 1)
    with pytest.raises(evidence.EvidenceError, match="too large"):
        evidence.validate(bucket(), NOW)


@pytest.mark.parametrize("mode", [0o755, 0o750, 0o777])
def test_directory_permissions_fail_closed(tmp_path, mode):
    store = tmp_path / "store"
    store.mkdir(mode=mode)
    store.chmod(mode)
    with pytest.raises(evidence.EvidenceError, match="unsafe store directory"):
        append(store)
    assert list(store.iterdir()) == []


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "mode", "large", "fifo"])
def test_unsafe_bucket_files_are_never_exported(tmp_path, kind):
    store = tmp_path / "store"
    append(store)
    path = store / evidence.filename(bucket())
    if kind in ("symlink", "fifo"):
        path.unlink()
        if kind == "symlink":
            target = tmp_path / "private"
            target.write_text("private-sensitive-value")
            path.symlink_to(target)
        else:
            os.mkfifo(path, 0o600)
    elif kind == "hardlink":
        os.link(path, tmp_path / "linked")
    elif kind == "mode":
        path.chmod(0o644)
    else:
        path.write_bytes(b"x" * (evidence.MAX_BYTES + 1))
    with pytest.raises((evidence.EvidenceError, OSError)):
        evidence.operate(store, "export", now=NOW)


def test_store_symlink_foreign_owner_and_repository_are_rejected(tmp_path, monkeypatch):
    store = tmp_path / "store"
    append(store)
    link = tmp_path / "link"
    link.symlink_to(store, target_is_directory=True)
    with pytest.raises(OSError):
        evidence.operate(link, "export", now=NOW)
    with pytest.raises(evidence.EvidenceError, match="outside the repository"):
        evidence.operate(
            SCRIPT.parent / "private-test-store", "append", evidence.encode(bucket()), now=NOW
        )
    monkeypatch.setattr(evidence.os, "getuid", lambda: -1)
    with pytest.raises(evidence.EvidenceError, match="unsafe store directory"):
        evidence.operate(store, "export", now=NOW)


def test_unexpected_entries_invalid_lock_and_slot_mismatch(tmp_path):
    store = tmp_path / "store"
    append(store)
    extra = store / "private-sensitive-value"
    extra.touch()
    with pytest.raises(evidence.EvidenceError, match="unexpected store entries"):
        evidence.operate(store, "export", now=NOW)
    extra.unlink()
    (store / ".lock").write_text("x")
    with pytest.raises(evidence.EvidenceError, match="invalid lock file"):
        evidence.operate(store, "export", now=NOW)
    (store / ".lock").write_text("")
    (store / evidence.filename(bucket())).rename(store / "staging-001.json")
    with pytest.raises(evidence.EvidenceError, match="slot mismatch"):
        evidence.operate(store, "export", now=NOW)


def test_lock_contention_and_pending_crash_cleanup(tmp_path):
    store = tmp_path / "store"
    append(store)
    with (store / ".lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            append(store)
    pending = store / ".pending"
    pending.write_bytes(b"partial validated bucket")
    pending.chmod(0o600)
    assert evidence.operate(store, "export", now=NOW)
    assert not pending.exists()


def test_failed_replace_preserves_previous_bucket(tmp_path, monkeypatch):
    store = tmp_path / "store"
    append(store)
    before = evidence.operate(store, "export", now=NOW)

    def fail(*args, **kwargs):
        raise OSError("private filesystem detail")

    monkeypatch.setattr(evidence.os, "replace", fail)
    with pytest.raises(OSError):
        append(store)
    assert not (store / ".pending").exists()
    assert evidence.operate(store, "export", now=NOW) == before


def test_clock_reversal_missing_store_and_bad_operation(tmp_path):
    store = tmp_path / "store"
    with pytest.raises(FileNotFoundError):
        evidence.operate(store, "export", now=NOW)
    assert not store.exists()
    append(store)
    with pytest.raises(evidence.EvidenceError, match="not closed"):
        evidence.operate(store, "export", now=BUCKET)
    for operation, now in (("bad", NOW), ("prune", -1), ("prune", True)):
        with pytest.raises(evidence.EvidenceError, match="invalid operation"):
            evidence.operate(store, operation, now=now)


class Stream:
    def __init__(self, raw=b""):
        self.buffer = io.BytesIO(raw)


def test_cli_success_rejection_and_no_private_error_text(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    monkeypatch.setattr(evidence.time, "time", lambda: NOW)
    monkeypatch.setattr(evidence.sys, "stdin", Stream(evidence.encode(bucket())))
    assert evidence.main(["append", "--store", str(store)]) == 0
    output = Stream()
    monkeypatch.setattr(evidence.sys, "stdout", output)
    assert evidence.main(["export", "--store", str(store)]) == 0
    assert json.loads(output.buffer.getvalue()) == evidence.validate(bucket(), NOW)
    assert evidence.main(["private-sensitive-value"]) == 1
    monkeypatch.setattr(evidence.sys, "stdin", Stream(b'{"path":"private-sensitive-value"}'))
    assert evidence.main(["append", "--store", str(store)]) == 1
    assert "private-sensitive-value" not in capsys.readouterr().err


def test_script_entrypoint(tmp_path, monkeypatch):
    monkeypatch.setattr(
        evidence.sys, "argv", [str(SCRIPT), "prune", "--store", str(tmp_path / "absent")]
    )
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert caught.value.code == 1
