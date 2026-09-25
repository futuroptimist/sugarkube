# token.place static 429 boundary-emulation design

## Status and purpose

This document proposes a future, independently implemented workflow named **static 429 boundary
emulation**. It is a staging-only observation of a pre-existing, narrowly scoped edge rule. It is
not a mode or stage of `tokenplace_incident_drill.py`, and it must never restore or call the removed
bounded quota-stimulus executor.

The historical experiment used a temporary WAF custom rule. It returned `429` for `/` and
`/api/v1/meta`, while `/livez` and `/healthz` returned `200`. The prior bounded quota executor
existed at `7c48c8184b69ee190863d29281ed97317d830474` and was removed by current commit
`d43154c670299baa3c1e43357f53ac2c8ece3cb0`. Its failure was correct and fail-closed:
`baseline-drift`, because the ordinary healthy baseline is `200/200/200/200` before stimulus.
Marker cleanup completed, no Deployment mutation occurred, and the WAF custom rule was deleted.

That result demonstrates only static boundary response selection. It is **not** evidence of genuine
quota exhaustion, limiter counter increments, threshold crossing, window reset, caller bucketing,
or any other rate-limit-counter behavior.

## Safety and lifecycle contract

Static 429 boundary emulation has its own classification and lifecycle:
`authorized-static-emulation` -> `preflight-validated` -> `observed` -> `evidence-reviewed` ->
`cleanup-proven`. It requires an explicit opt-in naming this lifecycle. A quota-exhaustion incident
or rehearsal authorization cannot select it, and its evidence cannot satisfy a quota-exhaustion
gate.

- **Staging only:** the sole canonical authority is `staging.token.place`; production is prohibited.
- **Observation only:** the workflow must not mutate a Deployment, image, replica count, registry,
  ServiceMonitor, Probe, Kubernetes resource, service, or application data plane. It must not
  create, update, enable, or widen the edge rule.
- **Exact target:** issue only `GET` observations over HTTPS to the canonical authority and exact
  paths `/`, `/api/v1/meta`, `/livez`, and `/healthz`. Reject redirects rather than following them.
  Reject aliases, query strings, fragments, user information, non-default ports, and path
  normalization.
- **Narrow expected result:** `/` and `/api/v1/meta` must each return exactly `429`. Separate
  control observations must prove `/livez` and `/healthz` each remain exactly `200`; neither health
  route is an emulation target.
- **Pre-existing configuration:** before any route observation, a human-reviewed attestation must
  identify and validate an already-present rule/configuration whose scope is exactly the canonical
  staging authority, the two emulated paths, and the intended method. The future observer receives
  no credentials or capability to manage that rule.
- **Short lifetime:** after the evidence is reviewed, an independently authorized owner must remove
  the rule immediately. The run is incomplete until a fresh, independently obtained cleanup
  attestation proves that exact rule is absent. Failure to prove removal is a failed, escalated run,
  never assumed cleanup.

The observer fails closed before or during the run on any unexpected status, redirect, transport or
TLS error, stale or future-dated evidence, hostname/path/method mismatch, rule scope broader than
the contract, missing independent health control, malformed attestation, or inability to prove
cleanup. It sends no retries or load and makes no claim about the origin that generated a response.

The default quota-exhaustion runner continues to require its ordinary healthy
`200/200/200/200` baseline before any stimulus. That invariant must not be weakened, bypassed, or
special-cased to accommodate static emulation. Genuine quota exhaustion requires authentic quota
state; rate-limit validation additionally requires evidence of counter and window behavior. Static
boundary emulation supplies neither.

## Evidence contract

Retain only a schema-versioned, privacy-safe record containing:

- the four exact route names and their integer statuses;
- UTC observation, review, and cleanup-attestation timestamps;
- a bounded rule-scope attestation (canonical host, exact methods and paths, rule identifier hash,
  and reviewer decision);
- a cleanup attestation for that same hashed identity; and
- SHA-256 hashes binding the reviewed configuration, observation record, and cleanup proof.

Do not retain tokens, cookies, credentials, response bodies, caller or request identifiers, query
strings, raw rule expressions, private URLs, or sensitive/request/response headers. Reject evidence
outside a reviewed freshness window and make its expiry explicit; hashes provide binding, not proof
that a claim is true or current.

## Future implementation and review plan

1. Specify a standalone observer and evidence schema outside `tokenplace_incident_drill.py`. Keep
   rule creation, editing, and deletion out of the tool; accept only signed or independently
   reviewed preflight and cleanup attestations.
2. Require a non-default `--lifecycle authorized-static-emulation` opt-in plus an authorization
   document bound to the staging host, exact rule hash, reviewer, rehearsal window, and expiry.
   Refuse production strings and ambiguous host representations at parsing and plan validation.
3. Build an offline plan first. A second independent reviewer must approve the immutable plan and
   evidence-retention fields before any network-capable invocation exists.
4. Implement one bounded observation of each emulation route and separate observations of both
   health controls, with redirects disabled and a strict timeout. Stop at the first contract
   violation. Never generate quota stimulus.
5. Record the privacy-safe result, require evidence review, then block completion until the exact
   cleanup attestation is fresh and hash-bound to the preflight rule identity.

Required unit tests must cover production and non-canonical-host refusal; missing opt-in; URL,
method, path, port, query, and redirect rejection; exact `429/429/200/200` acceptance; every
unexpected or mixed status; health-control independence; timeout, TLS, DNS, and other transport
failures; stale/future evidence; duplicate or unknown schema fields; broad or changed rule scope;
hash mismatch; privacy-field rejection; cleanup absence/failure; and proof that no Kubernetes,
Cloudflare-management, registry, Deployment, Probe, ServiceMonitor, or data-plane mutation path is
reachable. Tests must also prove that emulation evidence cannot satisfy the quota-exhaustion runner
and that its healthy baseline remains unchanged.

## Authorization boundary for a live rehearsal

This design document authorizes no live rehearsal. A later rehearsal requires a separate reviewed
change that contains the implemented tool and tests, names accountable application and edge-rule
owners, records an explicit staging-only approval and time box, binds the exact pre-existing rule
scope/hash, defines immediate owner-performed removal and escalation, and prohibits production.
Only after that change is merged and a second reviewer approves the immutable per-run plan may an
operator observe `staging.token.place`. Authorization to observe does not authorize rule mutation,
quota traffic, Kubernetes access, application mutation, or reuse of evidence for an incident.
