"""Inert version-1 chart records: data validation only, never operation authority.

All inputs are supplied bytes or explicit expected coordinates. No file, network,
archive, process, cluster, or lifecycle operations are implemented here.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

MAX_RECORD_BYTES = 64 * 1024
MAX_ARTIFACTS = 16
MAX_DEPTH = 32
ENVIRONMENTS = ("dev", "staging", "prod")
ACTIONS = ("render", "install", "upgrade", "rollback", "status", "verify")
PHASES = ("pre-acquisition", "pre-mutation")
HASH = r"[0-9a-f]{64}"
IDENTIFIER = r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?"
CHART_NAME = r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?"
_NUMERIC = r"(?:0|[1-9][0-9]*)"
_PRERELEASE = r"(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
VERSION = (
    rf"{_NUMERIC}\.{_NUMERIC}\.{_NUMERIC}"
    rf"(?:-{_PRERELEASE}(?:\.{_PRERELEASE})*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
REPOSITORY = r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}"
REVISION = r"(?:[0-9a-f]{40}|[0-9a-f]{64})"


class Refusal(ValueError):
    """A fixed diagnostic code; source text is never included in the message."""


def _require(condition, code):
    if not condition:
        raise Refusal(code)


def sha256(raw):
    """Hash original complete bytes, without decoding or reserialization."""
    _require(type(raw) is bytes, "INVALID_TYPE")
    return hashlib.sha256(raw).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "DUPLICATE_KEY")
        result[key] = value
    return result


def _number(_value):
    raise Refusal("INVALID_NUMBER")


def _integer(value):
    _require(len(value.lstrip("-")) <= 20, "INVALID_NUMBER")
    return int(value)


def _lexical_depth(text):
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            _require(depth <= MAX_DEPTH, "RECORD_DEPTH")
        elif char in "]}":
            depth -= 1
    # Syntax, matching delimiters and unterminated strings are checked by JSON.


def _safe_strings(value):
    if type(value) is str:
        # Printable ASCII deliberately excludes control characters, surrogates,
        # line separators and invisible formatting characters in every field/key.
        _require(all(32 <= ord(char) <= 126 for char in value), "INVALID_TEXT")
    elif type(value) is dict:
        for key, item in value.items():
            _safe_strings(key)
            _safe_strings(item)
    elif type(value) is list:
        for item in value:
            _safe_strings(item)


def decode_record(raw):
    """Bound and decode one strict JSON object; this alone is not validation."""
    _require(type(raw) is bytes, "INVALID_TYPE")
    _require(len(raw) <= MAX_RECORD_BYTES, "RECORD_SIZE")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        raise Refusal("INVALID_ENCODING") from None
    _require(not text.startswith("\ufeff"), "INVALID_ENCODING")
    _lexical_depth(text)
    try:
        result = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_constant=_number,
            parse_float=_number,
            parse_int=_integer,
        )
    except (json.JSONDecodeError, RecursionError):
        raise Refusal("INVALID_JSON") from None
    _require(type(result) is dict, "INVALID_TYPE")
    _safe_strings(result)
    return result


def _fields(record, names):
    _require(type(record) is dict, "INVALID_TYPE")
    _require(set(record) == set(names.split()), "INVALID_FIELDS")


def _text(value, pattern=None, maximum=512):
    _require(type(value) is str, "INVALID_TYPE")
    _require(1 <= len(value) <= maximum, "INVALID_TEXT")
    _safe_strings(value)
    if pattern is not None:
        _require(re.fullmatch(pattern, value) is not None, "INVALID_COORDINATE")


def _enum(value, choices):
    _text(value)
    _require(value in choices, "INVALID_ENUM")


def _version(record, policy=False):
    for field in ("schema_version", "policy_version") if policy else ("schema_version",):
        _require(type(record[field]) is int, "INVALID_TYPE")
        _require(record[field] == 1, "UNSUPPORTED_VERSION")


def _list(value, *, minimum=1, maximum=MAX_ARTIFACTS):
    _require(type(value) is list, "INVALID_TYPE")
    _require(minimum <= len(value) <= maximum, "INVALID_COUNT")


def _unique_texts(value, pattern=None, *, minimum=1):
    _list(value, minimum=minimum)
    for item in value:
        _text(item, pattern)
    _require(len(value) == len(set(value)), "DUPLICATE_ID")


def _url(value):
    _text(value, maximum=2048)
    _require(value.startswith("https://"), "INVALID_URL")
    _require(not any(char in value for char in "?#\\ "), "INVALID_URL")
    # Encoded controls and ambiguous percent escapes are disallowed too.
    _require(re.search(r"%(?![0-9A-Fa-f]{2})", value) is None, "INVALID_URL")
    _require(re.search(r"%(?:0[0-9a-f]|1[0-9a-f]|7f)", value, re.I) is None, "INVALID_URL")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise Refusal("INVALID_URL") from None
    _require(bool(parsed.hostname) and parsed.username is None, "INVALID_URL")
    _require(not parsed.query and not parsed.fragment, "INVALID_URL")
    _require(port is None or 1 <= port <= 65535, "INVALID_URL")
    # V1 uses an ASCII DNS host, optionally with an explicit numeric port.
    host = parsed.hostname
    _require(len(host) <= 253, "INVALID_URL")
    _require(
        all(
            re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
            for label in host.split(".")
        ),
        "INVALID_URL",
    )
    _require(not parsed.netloc.endswith(":"), "INVALID_URL")


def _chart(record):
    _text(record["chart_name"], CHART_NAME, 128)
    _text(record["chart_version"], VERSION, 128)
    _text(record["archive_sha256"], HASH)


def validate_lock(raw):
    """Return a structurally valid lock; reviews and expectations are unchecked."""
    record = decode_record(raw)
    _fields(record, "schema_version policy_version artifacts")
    _version(record, policy=True)
    _list(record["artifacts"])
    artifact_ids, review_ids = set(), set()
    for artifact in record["artifacts"]:
        _fields(
            artifact,
            "artifact_id chart_name chart_version package_url archive_size_bytes "
            "archive_sha256 review_id review_sha256",
        )
        _chart(artifact)
        _text(artifact["artifact_id"], IDENTIFIER)
        _text(artifact["review_id"], IDENTIFIER)
        _text(artifact["review_sha256"], HASH)
        _url(artifact["package_url"])
        size = artifact["archive_size_bytes"]
        _require(type(size) is int, "INVALID_TYPE")
        _require(1 <= size <= 2**63 - 1, "INVALID_SIZE")
        _require(artifact["artifact_id"] not in artifact_ids, "DUPLICATE_ID")
        _require(artifact["review_id"] not in review_ids, "DUPLICATE_ID")
        artifact_ids.add(artifact["artifact_id"])
        review_ids.add(artifact["review_id"])
    return record


def validate_review(raw):
    """Return review data without authenticating its author or accepting a chart."""
    record = decode_record(raw)
    _fields(
        record,
        "schema_version review_id artifact_id chart_name chart_version archive_sha256 "
        "reviewer evidence_kind evidence_references dependencies environments outcome",
    )
    _version(record)
    _chart(record)
    for field in ("review_id", "artifact_id"):
        _text(record[field], IDENTIFIER)
    _text(record["reviewer"], maximum=128)
    _enum(record["evidence_kind"], ("publisher-authenticated", "operator-review"))
    _unique_texts(record["evidence_references"])
    _unique_texts(record["dependencies"], IDENTIFIER, minimum=0)
    _unique_texts(record["environments"])
    for environment in record["environments"]:
        _enum(environment, ENVIRONMENTS)
    _enum(record["outcome"], ("accepted", "rejected"))
    return record


def validate_request(raw):
    """Return request data, never an approval receipt or reusable capability."""
    record = decode_record(raw)
    extra = ""
    if record.get("phase") == "pre-mutation":
        extra = " frozen_input_manifest_sha256 validated_output_sha256"
    _fields(
        record,
        "schema_version policy_version repository repository_revision lock_sha256 artifact_ids "
        "environment action namespace release operation_id phase" + extra,
    )
    _version(record, policy=True)
    _text(record["repository"], REPOSITORY, 256)
    _text(record["repository_revision"], REVISION)
    _text(record["lock_sha256"], HASH)
    _unique_texts(record["artifact_ids"], IDENTIFIER)
    _enum(record["environment"], ENVIRONMENTS)
    _enum(record["action"], ACTIONS)
    _enum(record["phase"], PHASES)
    for field in ("namespace", "release", "operation_id"):
        _text(record[field], IDENTIFIER, 63)
    for field in extra.split():
        _text(record[field], HASH)
    return record


@dataclass(frozen=True)
class ExpectedOperation:
    """Caller-supplied comparison data; constructing this grants no authority.

    package_urls contains (artifact_id, exact_url) tuples for the complete lock.
    artifact_ids is an ordered selection; all dependency IDs must be selected.
    """

    repository: str
    repository_revision: str
    lock_sha256: str
    artifact_ids: tuple[str, ...]
    package_urls: tuple[tuple[str, str], ...]
    environment: str
    action: str
    namespace: str
    release: str
    operation_id: str
    phase: str
    frozen_input_manifest_sha256: str | None = None
    validated_output_sha256: str | None = None


@dataclass(frozen=True)
class ValidatedRecords:
    """Validated data only: mutable nested dictionaries are not trusted state."""

    lock: dict
    reviews: tuple[dict, ...]
    request: dict
    lock_sha256: str
    review_sha256s: tuple[str, ...]


def validate_records(lock_bytes, review_bytes, request_bytes, *, expected):
    """Check all supplied records and explicit expectations, without side effects.

    One review is required for each lock artifact, with no extras. Review order
    is immaterial. Selected dependencies must be present and selected; cycles
    are refused. No signature, freshness, withdrawal or package verification is
    performed, and the return value cannot approve or execute any operation.
    """
    _require(type(expected) is ExpectedOperation, "INVALID_EXPECTATION")
    for field in (
        "repository repository_revision lock_sha256 environment action namespace "
        "release operation_id phase"
    ).split():
        _require(type(getattr(expected, field)) is str, "INVALID_EXPECTATION")
    _require(type(expected.artifact_ids) is tuple, "INVALID_EXPECTATION")
    _require(1 <= len(expected.artifact_ids) <= MAX_ARTIFACTS, "INVALID_EXPECTATION")
    _require(all(type(item) is str for item in expected.artifact_ids), "INVALID_EXPECTATION")
    for value in (expected.frozen_input_manifest_sha256, expected.validated_output_sha256):
        _require(value is None or type(value) is str, "INVALID_EXPECTATION")
    _require(type(review_bytes) in (list, tuple), "INVALID_TYPE")
    _require(1 <= len(review_bytes) <= MAX_ARTIFACTS, "INVALID_COUNT")
    lock = validate_lock(lock_bytes)
    request = validate_request(request_bytes)
    reviews = tuple(validate_review(raw) for raw in review_bytes)
    digest = sha256(lock_bytes)
    _require(digest == request["lock_sha256"], "DIGEST_MISMATCH")
    for field in request:
        if field in ("schema_version", "policy_version"):
            continue
        actual = tuple(request[field]) if field == "artifact_ids" else request[field]
        _require(actual == getattr(expected, field), "EXPECTATION_MISMATCH")
    if request["phase"] == "pre-acquisition":
        _require(
            expected.frozen_input_manifest_sha256 is None
            and expected.validated_output_sha256 is None,
            "INVALID_EXPECTATION",
        )
    artifacts = {item["artifact_id"]: item for item in lock["artifacts"]}
    _require(type(expected.package_urls) is tuple, "INVALID_EXPECTATION")
    _require(1 <= len(expected.package_urls) <= MAX_ARTIFACTS, "INVALID_EXPECTATION")
    _require(
        all(
            type(pair) is tuple and len(pair) == 2 and all(type(v) is str for v in pair)
            for pair in expected.package_urls
        ),
        "INVALID_EXPECTATION",
    )
    urls = dict(expected.package_urls)
    _require(len(urls) == len(expected.package_urls), "INVALID_EXPECTATION")
    _require(urls == {key: item["package_url"] for key, item in artifacts.items()}, "URL_MISMATCH")
    by_review = {item["review_id"]: item for item in reviews}
    _require(len(by_review) == len(reviews), "DUPLICATE_ID")
    _require(set(by_review) == {item["review_id"] for item in artifacts.values()}, "REVIEW_SET")
    hashes = {item["review_id"]: sha256(raw) for item, raw in zip(reviews, review_bytes)}
    dependencies = {}
    for key, artifact in artifacts.items():
        review = by_review[artifact["review_id"]]
        _require(hashes[review["review_id"]] == artifact["review_sha256"], "DIGEST_MISMATCH")
        for field in ("artifact_id", "chart_name", "chart_version", "archive_sha256"):
            _require(artifact[field] == review[field], "IDENTITY_MISMATCH")
        dependencies[key] = review["dependencies"]
        _require(set(dependencies[key]) <= artifacts.keys(), "UNKNOWN_ARTIFACT")
    selected = set(request["artifact_ids"])
    _require(selected <= artifacts.keys(), "UNKNOWN_ARTIFACT")
    for key in selected:
        review = by_review[artifacts[key]["review_id"]]
        _require(set(dependencies[key]) <= selected, "UNSELECTED_DEPENDENCY")
        _require(request["environment"] in review["environments"], "ENVIRONMENT_MISMATCH")
        _require(review["outcome"] == "accepted", "REVIEW_NOT_ACCEPTED")
    visited, active = set(), set()

    def visit(key):
        _require(key not in active, "DEPENDENCY_CYCLE")
        if key in visited:
            return
        active.add(key)
        for dependency in dependencies[key]:
            visit(dependency)
        active.remove(key)
        visited.add(key)

    for key in artifacts:
        visit(key)
    return ValidatedRecords(
        lock, reviews, request, digest, tuple(hashes[r["review_id"]] for r in reviews)
    )
