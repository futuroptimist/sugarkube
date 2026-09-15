# token.place encrypted-completion observability contract

This repository-only slice declares a generic scheduled producer and sanitized metrics contract. It
is **disabled** and does not authorize installation, activation, a live request, or any staging or
production mutation. The descriptor records only application/environment, cadence, timeout,
concurrency, hourly/daily quota, exact route/method, shared bucket, and a finite failure-stage list.

The evidence schema accepts only timestamps, duration, two outcome booleans, and one finite failure
stage. Metrics distinguish completion/decryption success, last successful completion, last attempt
freshness, end-to-end completion duration (not HTTP polling latency), each bounded failure stage,
staleness, and intentional disablement. Prompts, responses, payloads, ciphertext, cryptographic
keys, credentials, authorization data, request identities, and raw URLs are not schema fields.

The existing DSPACE isolated `/chat` synthetic remains the only recurring inference journey. It
validates a DSPACE application path but does not prove token.place's application-owned E2EE client
completion and decryption contract. Reusing it as token.place evidence would therefore be false;
this slice adds no runner and leaves the new token.place producer disabled.

A real E2EE producer requires application-owned client code, reviewed credentials/runtime
provisioning, and separate staging authorization. Until those exist, this repository proves only
schema, quota, sanitization, dashboard/rule, and fixture behavior—not runtime E2EE functionality or
staging/production qualification.
