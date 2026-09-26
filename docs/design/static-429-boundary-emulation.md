# Static 429 boundary emulation design

## Purpose and experiment record

**Static 429 boundary emulation** is the name of a proposed, staging-only workflow for checking
that route-specific HTTP 429 responses at the public boundary are classified without mistaking
them for an application outage. It is a separate lifecycle and evidence class from both genuine
quota exhaustion and rate-limit counter validation. It is not a mode, stage, preflight, or success
condition of `scripts/tokenplace_incident_drill.py`.

A bounded quota-stimulus executor previously existed at commit
`7c48c8184b69ee190863d29281ed97317d830474` and was removed by commit
`d43154c670299baa3c1e43357f53ac2c8ece3cb0`. This design does not restore, replace, or authorize
that executor.

The motivating temporary WAF custom-rule experiment returned 429 for `/` and `/api/v1/meta`, while
`/livez` and `/healthz` returned 200. The ordinary quota runner correctly failed closed with
`baseline-drift`: its healthy baseline requires the exact status tuple `200/200/200/200` before
stimulus. Marker cleanup completed, no Deployment mutation occurred, and the WAF custom rule was
deleted. These observations demonstrate only a static boundary response. They are **not** evidence
of genuine quota exhaustion, consumption of a quota, or rate-limit counter behavior.

## Safety and authorization contract

The future workflow must enforce all of these invariants:

- **Staging only:** the sole host is the canonical `staging.token.place`; production is prohibited.
  Host aliases, arbitrary hosts, IP literals, ports, query strings, and user-supplied paths are
  rejected.
- **Explicit opt-in:** a dedicated `static-429-boundary-emulation` lifecycle and a purpose-specific
  acknowledgement are required. Quota-exhaustion flags or approvals cannot authorize it.
- **Observation only:** it must not mutate a Deployment, image, replica count, ServiceMonitor,
  Probe, registry, Service, Kubernetes resource, or application data plane. It must not create or
  modify the boundary rule.
- **Narrow route contract:** observations use HTTPS `GET` requests only, against the exact paths
  `/` and `/api/v1/meta`; redirects are disabled and rejected. The expected emulated status is 429
  for both routes.
- **Independent health controls:** separate observations must prove exact 200 responses from both
  `/livez` and `/healthz`. These controls are never emulation targets.
- **Pre-existing configuration:** before making any emulation observation, an independently
  authorized, pre-existing rule/configuration must be attested and validated as staging-only,
  host-exact, path-exact, method-exact, and status-exact. The workflow may neither widen nor repair
  it. Broad or unprovable scope fails closed.
- **Removal:** after evidence review, the rule must be removed immediately by its separately
  authorized owner. The workflow remains incomplete until a fresh, independently verifiable
  cleanup attestation proves the exact rule is absent. It must never claim cleanup merely because
  requests stopped or the rule cannot be found by an underprivileged observer.

Every phase fails closed on an unexpected status, redirect, transport or TLS error, stale evidence,
broad or changed rule scope, host/path mismatch, missing health control, or inability to prove
cleanup. Failure stops further observation; it never falls back to a different host or path and
never invokes quota-exhaustion recovery. The immutable plan must define a short evidence freshness
window (no more than five minutes) and reject future, unordered, or expired timestamps.

The default quota-exhaustion runner continues to require its ordinary healthy
`200/200/200/200` baseline. That baseline and its `baseline-drift` behavior must not be weakened,
bypassed, relabeled, or special-cased to accommodate static emulation.

## Evidence contract

Retained evidence is privacy-safe and schema-versioned. It contains only:

- UTC observation timestamps and freshness bounds;
- the four route labels and their numeric statuses;
- an attestation that rule scope was exact, plus its timestamp and SHA-256 hash;
- an attestation that the exact rule was removed, plus its timestamp and SHA-256 hash; and
- hashes binding the reviewed plan, observations, and attestations.

Evidence must not contain tokens, cookies, response bodies, sensitive headers, credentials,
caller or source identities, request identifiers, query strings, or rule secrets. A hash is a
binding commitment, not a substitute for independent review or proof of cleanup. Reports must
label the result `static-429-boundary-emulation`; they must not use `quota-exhaustion`,
`rate-limit-validated`, or equivalent claims.

## Future implementation plan

Any implementation requires a separate pull request and independent security/operations review:

1. Define a small, independently invoked tool or manual workflow with an immutable, versioned plan
   and evidence schema. Do not add it to `tokenplace_incident_drill.py`.
2. Validate explicit opt-in, staging identity, canonical host, exact method/path allowlists,
   redirect rejection, evidence freshness, and the pre-existing narrow-scope attestation before
   allowing observations.
3. Observe the two emulated routes and both health controls with bounded, sequential requests and
   no retries; record only the privacy-safe projection above.
4. Stop for human evidence review, then require the rule owner to remove the configuration outside
   the observation tool. Verify and record exact cleanup before reporting completion.
5. Add unit tests for production/alias rejection, missing opt-in, attempts to create or change a
   rule, all host/method/path deviations, redirects, every unexpected or mixed status, transport
   errors, stale/future evidence, overbroad or changed scope, absent health controls, privacy-field
   rejection, hash mismatch, cleanup failure, and the successful `429/429/200/200` observation and
   cleanup sequence. Tests must also prove the ordinary quota runner still rejects that tuple as
   `baseline-drift` and requires `200/200/200/200`.

No later live rehearsal is authorized by this document or by merging an implementation. A live
staging rehearsal requires a new, time-bounded written approval from the staging service owner and
the boundary-rule owner, review of the exact immutable plan and exact rule identifier/scope, named
operators for observation and removal, and an agreed cleanup deadline. Production remains
prohibited. Missing, expired, or ambiguous authorization permits offline validation only and no
contact with the staging endpoint or boundary provider.
