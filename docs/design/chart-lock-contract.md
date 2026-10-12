# Offline chart lock contract

This is PR A of K057: an inert data contract. Nothing imports it from an existing
command or workflow. Valid data is **not approval**, admission, a receipt, or a
capability. K057, K056, and K051 remain open. No chart has been admitted.

The module uses only the Python standard library. It accepts supplied bytes and
explicit expected coordinates; it does not read files, log source text, acquire
archives, parse YAML, start processes, or contact a cluster. It has no command
line interface. Existing chart and lifecycle behavior remains unchanged.

## API and acceptance boundary

`scripts/chart_lock_contract.py` provides:

- `decode_record(raw)`: strict, bounded JSON decoding only.
- `validate_lock(raw)`, `validate_review(raw)`, `validate_request(raw)`: structural
  validation of one record. These do not check other records or caller expectations.
- `validate_records(lock_bytes, review_bytes, request_bytes, expected=...)`:
  structural validation plus byte hashes, cross-record checks, and explicit
  expected coordinates. `review_bytes` must be a list or tuple of bytes.
- `sha256(raw)`: SHA-256 of the original complete bytes.

Success returns data. Refusal raises `Refusal`, a `ValueError` with one fixed code.
No source text is copied into the exception message. A caller must not log raw
input or treat a returned object as live permission. Nested returned dictionaries
remain mutable; they must never serve as trusted operation state.

`ExpectedOperation` requires the expected repository, full revision, raw lock
hash, ordered artifact IDs, exact package URLs for the **complete lock**, canonical
environment, action, namespace, release, operation ID, and phase. Package URLs are
a tuple of `(artifact_id, exact_url)` tuples. Each ID appears once. Comparison
preserves URL spelling and selected artifact order. Pre-mutation expectations
also require both manifest and output hashes. Pre-acquisition expectations must
leave both hashes as `None`.

The expected values must eventually come from an independently trusted source.
Copying them from the same untrusted request proves only internal consistency.
An expected hash is still not an authenticated owner decision.

## Version 1 fields

Every object has exactly its documented fields. All hashes are lowercase, 64-digit
SHA-256 strings. All strings are nonempty printable ASCII; this conservative first
version refuses controls, line separators, invisible Unicode, and surrogate code
points, even in unknown field names. Schema and policy versions are integer `1`,
never Boolean or numeric strings.

IDs use lowercase letters, digits, and internal hyphens, with at most 64 characters.
Namespace, release, and operation IDs are capped at 63. Chart names additionally
allow internal dots and underscores and are capped at 128. Chart versions are
bounded semantic versions, including optional release and build suffixes; numeric
components and numeric release identifiers cannot have leading zeroes.

### Lock

| Field | Meaning |
| --- | --- |
| `schema_version`, `policy_version` | Both integer `1` |
| `artifacts` | One through 16 artifact objects |

Each artifact contains:

| Field | Meaning |
| --- | --- |
| `artifact_id` | Unique artifact ID |
| `chart_name`, `chart_version` | Exact chart coordinates |
| `package_url` | Exact HTTPS archive destination, at most 2,048 characters |
| `archive_size_bytes` | Integer from 1 through 2^63 minus 1, never Boolean |
| `archive_sha256` | Digest of the proposed compressed archive bytes |
| `review_id` | Unique ID of its content review |
| `review_sha256` | Digest of the complete original UTF-8 review bytes |

URLs require an explicit ASCII DNS host and may have a port from 1 through 65535.
User information, query strings, fragments, backslashes, spaces, controls,
malformed percent escapes, and percent-encoded ASCII controls are refused.
Empty query or fragment delimiters are also refused. Version 1 does not support
IPv6 literals or international host names. Nothing resolves or fetches a URL.
Exact equality is intentional: host case and alternate encodings are not normalized.

The integer size limit is a representation limit, not a qualified archive ceiling.
The later package stage must enforce its own compressed and expanded size limits.

### Content review

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer `1` |
| `review_id`, `artifact_id` | Exact references to the lock entry |
| `chart_name`, `chart_version`, `archive_sha256` | Must match the lock |
| `reviewer` | Descriptive name, at most 128 characters |
| `evidence_kind` | `publisher-authenticated` or `operator-review` |
| `evidence_references` | One through 16 unique text references, each at most 512 characters |
| `dependencies` | Zero through 16 unique artifact IDs from this lock |
| `environments` | One or more unique canonical environments |
| `outcome` | `accepted` or `rejected` |

Every artifact requires exactly one matching review, including unselected artifacts.
Extra, missing, or duplicate review IDs refuse the entire bundle. Review input order
is immaterial. Every dependency must exist in the lock; cycles are refused. Selected
artifacts require their entire dependency closure to be selected. This is an explicit
record inventory, not evidence that dependencies are bundled inside an archive.
Package inspection remains future work.

Only selected artifacts must have an `accepted` outcome and include the requested
environment. A structurally valid `rejected` review is useful data but cannot pass
bundle validation for a selected artifact. Neither outcome, reviewer identity,
evidence references, nor the label `publisher-authenticated` authenticates evidence.

### Operation request

| Field | Meaning |
| --- | --- |
| `schema_version`, `policy_version` | Both integer `1` |
| `repository` | Explicit `owner/name`, compared exactly |
| `repository_revision` | Full lowercase 40- or 64-digit Git object ID |
| `lock_sha256` | Digest of the original complete lock bytes |
| `artifact_ids` | One through 16 unique, ordered selected IDs |
| `environment` | `dev`, `staging`, or `prod` |
| `action` | `render`, `install`, `upgrade`, `rollback`, `status`, or `verify` |
| `namespace`, `release`, `operation_id` | Explicit expected operation coordinates |
| `phase` | `pre-acquisition` or `pre-mutation` |
| `frozen_input_manifest_sha256` | Required only for pre-mutation |
| `validated_output_sha256` | Required only for pre-mutation |

Repository owners start with an ASCII letter or digit and may include hyphens,
up to 39 characters. Repository names start with a letter, digit, or underscore
and may include dots and hyphens, up to 100 characters. A revision string does not
prove a clean checkout or establish repository identity.

The manifest and output digests describe complete frozen and validated byte sets;
this module does not create, inspect, or qualify either set. Adapters must later
apply their narrower supported action and environment sets. Aliases such as `int`
and `production` are not canonical values here. Future adapters must normalize
aliases before seeking admission. An operation ID is data; no replay protection,
randomness guarantee, or state machine is supplied by this module.

## Strict decoding and refusal codes

Each record is capped at **65,536 bytes before UTF-8 decoding**. UTF-8 BOMs and
invalid UTF-8 refuse. Lexical container depth is capped at **32 before JSON object
construction**, counting the root container as one and ignoring delimiters inside
strings. JSON syntax is then checked normally. Duplicate decoded keys, including
escaped equivalents, refuse. All floating-point and nonfinite number spellings
refuse; the formats have no floating-point fields. Integer tokens are capped at
20 digits before conversion. Record and review counts are capped at **16**.

| Codes | Meaning |
| --- | --- |
| `RECORD_SIZE`, `RECORD_DEPTH` | Input resource ceiling exceeded |
| `INVALID_ENCODING`, `INVALID_JSON`, `DUPLICATE_KEY`, `INVALID_NUMBER` | Strict decoding failed |
| `INVALID_TYPE`, `INVALID_FIELDS`, `INVALID_TEXT` | Wrong type, field set, or text |
| `INVALID_COORDINATE`, `INVALID_ENUM`, `INVALID_SIZE`, `INVALID_URL` | Invalid field value |
| `UNSUPPORTED_VERSION`, `INVALID_COUNT`, `DUPLICATE_ID` | Version or collection rule failed |
| `INVALID_EXPECTATION`, `EXPECTATION_MISMATCH`, `URL_MISMATCH` | Expected context is invalid or differs |
| `DIGEST_MISMATCH`, `IDENTITY_MISMATCH`, `REVIEW_SET` | Bytes, coordinates, or review inventory differs |
| `UNKNOWN_ARTIFACT`, `UNSELECTED_DEPENDENCY`, `DEPENDENCY_CYCLE` | Invalid selection or dependency graph |
| `ENVIRONMENT_MISMATCH`, `REVIEW_NOT_ACCEPTED` | Selected review does not cover the request |

The three schemas in `config/chart-locks/` document the decoded shapes. JSON Schema
alone cannot enforce duplicate lexical keys, original byte identity, resource
ceilings before construction, or cross-record expectations. JSON Schema integer
semantics also differ from the strict lexical integer rule. The Python validator
is the complete offline acceptance gate; schema validation is not a substitute.

## Synthetic examples and tests

`tests/fixtures/chart_locks/` contains only synthetic records: `example.invalid`
URLs, an invented reviewer, a fictional repository and revision, and deterministic
digests of harmless fixture bytes. The fixture-local `.gitattributes` preserves LF
bytes across Windows checkouts so the lock and review hashes remain exact. There
is no production lock under `config/chart-locks/`.

Run the focused suite using already installed Python:

```sh
python -m unittest discover -s tests -p test_chart_lock_contract.py -v
```

The tests cover valid acquisition and pre-mutation requests, exact byte hashes,
reformatting, size/depth/count boundaries, malformed JSON and coordinates, forged
approval fields, cross-record substitutions, and dependency refusal. Import and
validation are exercised with file access, sockets, URL opening, and process
creation blocked, while captured output must remain empty.

## Trust and future work

No accepted record establishes provenance, freshness, withdrawal status, owner
admission, cluster identity, archive integrity, safe YAML construction, or rollout
success. No credentials or real packages are involved. This module cannot issue
approval or perform a supervised operation. Existing callers remain unchanged.

Guarded parsing, verified acquisition, a trusted owner launcher, process-local
single-use admission, and lifecycle integration each require separate review.
Merging and operational gates belong to the owner. Green tests for this contract
alone do not close K057, K056, or K051.
