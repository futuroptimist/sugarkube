# Encrypted-completion observability contract

Issue #2809 is represented by a repository-only, intentionally disabled producer descriptor at
`config/observability/encrypted-completion.json`. It declares the application and environment,
enabled state, cadence, timeout, concurrency, exact route and method, shared hourly and daily quota
budget, and the complete failure-stage vocabulary. Its `requestMultiplicity` is deliberately null:
the application owner has not qualified how many HTTP requests one encrypted journey requires.
The schema has no unlimited mode, and an enabled producer must declare a positive multiplicity.
Merely merging or installing these files does not schedule or execute a request.

The generic quota validator reads this descriptor alongside the blackbox quota inventory. Enabled
completion schedules consume
`ceil(window / cadence) * concurrency * requestMultiplicity` requests. Concurrency counts parallel
journeys; multiplicity independently counts declared requests per journey and does not invent a
polling or retry bound. Blackbox and completion volumes are added when they have the same
application, environment, and bucket, and their limit and safety-margin policies must agree. A
schedule at or above its safety-adjusted hourly or daily limit fails closed. Exemptions match only
the declared exact path and method; no claim is made that the application-owned route or budget has
been qualified against staging or production. Disabled declarations consume no quota but must
retain complete metadata so activation cannot inherit an ambiguous contract. Blackbox declarations
retain their explicit reviewed unlimited contract; completion declarations cannot be unlimited.

The bounded evidence schema accepts only identity, timestamps, end-to-end duration, a success or
failure outcome, one finite failure stage, the prior last-success timestamp, and Boolean assertions
that client-side decryption and response validation succeeded. It rejects extra fields. Its metrics
distinguish monitoring enabled state, last attempt freshness, success, last successful completion,
end-to-end completion duration, and failure stage. Failed attempts preserve the last successful
completion timestamp, and evidence timestamps more than five minutes in the future are rejected.
Completion duration is deliberately distinct from relay HTTP polling latency.
The lifecycle metric is deterministic: a disabled producer is `disabled`; an enabled producer with
no evidence is `never_attempted`; a timely success is `fresh`; a timely unsuccessful attempt is
`failed`; and any attempt older than cadence plus timeout is `stale`. The injectable evaluation
clock permits at most five minutes of future skew for attempt, completion, and prior-success times.
Disabled producers emit only declared disabled lifecycle state and reject execution evidence.

## Application-owned boundary

This repository has no safe application-owned client implementation or credential contract with
which to perform the real token.place encrypted journey. Consequently this slice supplies no
request producer, timer, service, secret reference, prompt, response, encrypted material, or request
identity. It does not claim end-to-end runtime coverage. A later application-owned client may emit
the sanitized evidence only after it has actually completed client-side decryption and validated
the response, and activation requires separate review and authorization. Test fixtures are
sanitized client assertions, not proof that this repository performed decryption.

The existing DSPACE `/chat` synthetic is reused as evidence that recurring inference already has a
bounded scheduling lifecycle. It cannot prove token.place client-side decryption: its committed
result contract is an isolated, intercepted, non-mutating DSPACE journey. Creating another DSPACE
journey here would duplicate recurring inference without closing the application-owned gap, so no
duplicate producer was added.

Repository verification is non-mutating:

```bash
pytest -q tests/test_encrypted_completion_contract.py tests/test_validate_probe_quotas.py
python3 scripts/validate_probe_quotas.py --env staging
python3 scripts/validate_probe_quotas.py --env prod
```

Staging and production execution, qualification, and observation windows remain unperformed.
