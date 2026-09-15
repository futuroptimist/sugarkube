# Encrypted-completion observability contract

Issue #2809 is represented by a repository-only, intentionally disabled producer descriptor at
`config/observability/encrypted-completion.json`. It declares the application and environment,
enabled state, cadence, timeout, concurrency, exact route and method, shared hourly and daily quota
budget, and the complete failure-stage vocabulary. Merely merging or installing these files does
not schedule or execute a request.

The generic quota validator reads this descriptor alongside the blackbox quota inventory. Enabled
completion schedules consume `ceil(window / cadence) * concurrency` requests in their shared
application/environment/bucket. A schedule at or above its safety-adjusted hourly or daily limit
fails closed. Exemptions match only an exact path and method. Disabled declarations consume no
quota but must retain complete metadata so activation cannot inherit an ambiguous contract.

The bounded evidence schema accepts only identity, timestamps, end-to-end duration, a success or
failure outcome, one finite failure stage, and Boolean assertions that client-side decryption and
response validation succeeded. It rejects extra fields. Its metrics distinguish monitoring enabled
state, last attempt freshness, success, last successful completion, end-to-end completion duration,
and failure stage. Completion duration is deliberately distinct from relay HTTP polling latency.
An enabled producer with an old or absent attempt metric is stale; a producer with
`encrypted_completion_monitoring_enabled` equal to zero is intentionally disabled.

## Application-owned boundary

This repository has no safe application-owned client implementation or credential contract with
which to perform the real token.place encrypted journey. Consequently this slice supplies no
request producer, timer, service, secret reference, prompt, response, encrypted material, or request
identity. It does not claim end-to-end runtime coverage. A later application-owned client may emit
the sanitized evidence only after it has actually completed client-side decryption and validated
the response, and activation requires separate review and authorization.

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
