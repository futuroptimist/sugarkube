#!/usr/bin/env python3
"""Local-only retention of validated aggregate buckets; never a traffic collector."""

import argparse
import fcntl
import json
import math
import os
import stat
import sys
import time
from contextlib import contextmanager
from pathlib import Path

BUCKET_SECONDS = 300
RETENTION_SECONDS = 86400
SLOTS = RETENTION_SECONDS // BUCKET_SECONDS
MAX_BYTES = 65536
MAX_VALUE = 10**12
ENVIRONMENTS = ("staging", "prod")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "other")
STATUSES = ("1xx", "2xx", "3xx", "4xx", "5xx", "other")
# token.place #1771's application-owned public quota labels, not HTTP route labels.
ROUTES = (
    "root",
    "public_metadata",
    "public_version",
    "api_v1",
    "api_v2",
    "operational",
    "static",
    "control_plane",
    "other_known",
    "unmatched",
)
OUTCOMES = ("accepted", "exempt", "rejected")
REASONS = ("none", "hourly_limit", "daily_limit", "other_limit", "other_rejection")
COVERAGE = ("complete", "partial", "unavailable")
SCRAPE = {
    "samples_max",
    "series_added_max",
    "duration_ms_max",
    "size_bytes_max",
    "route_series_max",
}
RUNTIME = {"restarts", "ooms"}
FIELDS = {
    "schema_version",
    "environment",
    "bucket",
    "coverage",
    "http",
    "quota",
    "scrape",
    "runtime",
}
FILES = {f"{env}-{slot:03d}.json" for env in ENVIRONMENTS for slot in range(SLOTS)}


class EvidenceError(ValueError):
    """Static errors never echo an input, path, or exception body."""


def exact(value, fields):
    if type(value) is not dict or set(value) != fields:
        raise EvidenceError("invalid fields")


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= MAX_VALUE:
        raise EvidenceError("invalid aggregate")


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise EvidenceError("duplicate field")
        result[key] = value
    return result


def decode(raw):
    if len(raw) > MAX_BYTES:
        raise EvidenceError("bucket too large")
    try:
        return json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise EvidenceError("invalid bucket JSON") from None


def encode(value):
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def validate(record, now):
    exact(record, FIELDS)
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise EvidenceError("invalid version")
    if record["environment"] not in ENVIRONMENTS:
        raise EvidenceError("invalid environment")
    bucket = record["bucket"]
    if type(bucket) is not int or not 0 <= bucket <= 2**53 or bucket % BUCKET_SECONDS:
        raise EvidenceError("invalid bucket time")
    if bucket + BUCKET_SECONDS > now:
        raise EvidenceError("bucket is not closed")
    exact(record["coverage"], {"http", "quota", "scrape", "runtime"})
    if any(value not in COVERAGE for value in record["coverage"].values()):
        raise EvidenceError("invalid coverage")
    for field, domains in (
        ("http", (METHODS, STATUSES)),
        ("quota", (ROUTES, METHODS, OUTCOMES, REASONS)),
    ):
        rows = record[field]
        if type(rows) is not list or len(rows) > math.prod(map(len, domains)):
            raise EvidenceError("invalid rows")
        seen = set()
        for row in rows:
            if type(row) is not list or len(row) != len(domains) + 1:
                raise EvidenceError("invalid row")
            if any(
                type(label) is not str or label not in domain for label, domain in zip(row, domains)
            ):
                raise EvidenceError("invalid label")
            key = tuple(row[:-1])
            if key in seen:
                raise EvidenceError("duplicate row")
            seen.add(key)
            number(row[-1])
            if field == "quota" and ((row[2] == "rejected") == (row[3] == "none")):
                raise EvidenceError("invalid quota combination")
        if record["coverage"][field] == "unavailable" and rows:
            raise EvidenceError("unavailable data must be empty")
    for field, fields in (("scrape", SCRAPE), ("runtime", RUNTIME)):
        exact(record[field], fields)
        coverage = record["coverage"][field]
        for value in record[field].values():
            if coverage == "unavailable" and value is not None:
                raise EvidenceError("unavailable data must be null")
            if coverage == "complete" or value is not None:
                number(value)
    # Canonicalize row order so an identical replay is idempotent.
    result = {**record, "http": sorted(record["http"]), "quota": sorted(record["quota"])}
    if len(encode(result)) > MAX_BYTES:
        raise EvidenceError("bucket too large")
    return result


def filename(record):
    return f"{record['environment']}-{record['bucket'] // BUCKET_SECONDS % SLOTS:03d}.json"


def check_file(fd):
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or info.st_size > MAX_BYTES
    ):
        raise EvidenceError("unsafe store file")


@contextmanager
def private_store(path, create):
    """Require a dedicated owner-only directory; pin all operations to its descriptor."""
    target = Path(path).resolve()
    repository = Path(__file__).resolve().parents[1]
    if target == repository or repository in target.parents:
        raise EvidenceError("store must be outside the repository")
    if create:
        try:
            Path(path).mkdir(mode=0o700)
        except FileExistsError:
            pass
    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.getuid():
            raise EvidenceError("unsafe store directory")
        lock = os.open(
            ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory
        )
        try:
            check_file(lock)
            if os.fstat(lock).st_size:
                raise EvidenceError("invalid lock file")
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            names = set(os.listdir(directory))
            if names - FILES - {".lock", ".pending"}:
                raise EvidenceError("unexpected store entries")
            if ".pending" in names:
                pending = os.open(
                    ".pending", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
                )
                try:
                    check_file(pending)
                finally:
                    os.close(pending)
                os.unlink(".pending", dir_fd=directory)
            yield directory
        finally:
            os.close(lock)
    finally:
        os.close(directory)


def records(directory, now):
    """Validate every stored record before pruning or producing any export."""
    result = []
    for name in sorted(set(os.listdir(directory)) & FILES):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as handle:
            check_file(handle.fileno())
            record = validate(decode(handle.read(MAX_BYTES + 1)), now)
        if filename(record) != name:
            raise EvidenceError("bucket slot mismatch")
        result.append(record)
    return result


def operate(path, operation, raw=None, *, now=None):
    """Write one finalized bucket, prune, or return validated JSONL; no network I/O."""
    now = int(time.time()) if now is None else now
    if type(now) is not int or now < 0 or operation not in ("append", "prune", "export"):
        raise EvidenceError("invalid operation")
    incoming = validate(decode(raw), now) if operation == "append" else None
    if incoming is not None and incoming["bucket"] <= now - RETENTION_SECONDS:
        raise EvidenceError("expired input")
    with private_store(path, create=operation == "append") as directory:
        existing = records(directory, now)
        live = [r for r in existing if r["bucket"] > now - RETENTION_SECONDS]
        if incoming is not None:
            same = [r for r in live if filename(r) == filename(incoming)]
            if same and same[0] != incoming:
                raise EvidenceError("conflicting bucket")
        for record in existing:
            if record["bucket"] <= now - RETENTION_SECONDS:
                os.unlink(filename(record), dir_fd=directory)
        if incoming is not None:
            fd = os.open(
                ".pending",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(encode(incoming))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(
                    ".pending", filename(incoming), src_dir_fd=directory, dst_dir_fd=directory
                )
            finally:
                if ".pending" in os.listdir(directory):
                    os.unlink(".pending", dir_fd=directory)
        os.fsync(directory)
        if operation == "export":
            return b"".join(
                encode(r) for r in sorted(live, key=lambda r: (r["bucket"], r["environment"]))
            )
    return b""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise EvidenceError("invalid invocation")


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument("operation", choices=("append", "prune", "export"))
    parser.add_argument("--store", required=True, help="dedicated private local directory")
    try:
        args = parser.parse_args(argv)
        raw = sys.stdin.buffer.read(MAX_BYTES + 1) if args.operation == "append" else None
        output = operate(args.store, args.operation, raw)
        if output:
            sys.stdout.buffer.write(output)
        return 0
    except (EvidenceError, OSError, ValueError, TypeError, OverflowError, RecursionError):
        print("aggregate evidence rejected; no private details emitted", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
