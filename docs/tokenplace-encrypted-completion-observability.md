# token.place encrypted-completion observability contract

Issue #2809 is represented here as a **disabled, repository-only contract**. The descriptor
records its application and environment, schedule, timeout, concurrency, exact route and method,
shared hourly and daily quota bucket, and finite failure-stage vocabulary. It contains no prompt,
response, ciphertext, key, credential, or request identity.

The existing DSPACE isolated `/chat` synthetic is intentionally not copied: it uses intercepted
transport and proves only its pinned DSPACE journey. It cannot prove token.place client-side
decryption. A token.place application-owned client and credentials are therefore required before
activation. This repository neither knows the payload format nor performs a live request.

When that client eventually supplies bounded evidence, `encrypted_completion_metrics.py` accepts
only timestamps, duration, booleans, and one enumerated failure stage. Success means both client-side
decryption and completion validation succeeded. Attempt freshness, last success, completion duration
(distinct from HTTP polling latency), failures, staleness, and the disabled state remain separately
queryable. The quota validator checks enabled schedules generically and aggregates matching
application/environment/bucket entries; exemptions match the exact path and method.

No staging or production activation is part of this contract. Qualification requires a separately
authorized rollout and a real application-owned E2EE client journey.
