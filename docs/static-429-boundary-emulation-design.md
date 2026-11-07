# Static 429 boundary emulation design

This document proposes a future, independently reviewed **static 429 boundary emulation**
workflow. It is a staging-only boundary check, not a quota-exhaustion mode or stage of
`scripts/tokenplace_incident_drill.py`. Production use is prohibited. This design does not
authorize a rehearsal, create a tool, or change any live system.

## Historical observation and limits

A bounded quota-stimulus executor existed at commit
`7c48c8184b69ee190863d29281ed97317d830474` and was removed by commit
`d43154c670299baa3c1e43357f53ac2c8ece3cb0`. It must not be restored for this workflow.

In the temporary WAF custom-rule experiment, `GET /` and `GET /api/v1/meta` returned `429`, while
`GET /livez` and `GET /healthz` returned `200`. The ordinary quota-exhaustion runner correctly
failed closed with `baseline-drift`: its healthy baseline requires `200/200/200/200` before any
stimulus. Marker cleanup completed, no Deployment mutation occurred, and the WAF custom rule was
deleted.

That result demonstrates only static response behavior at a narrowly configured boundary. It is
not evidence of a rate-limit counter, counter increments, threshold enforcement, window reset,
caller attribution, genuine quota exhaustion, or application-originated `429` responses.

## Classification and safety contract

The lifecycle name is `static-429-boundary-emulation`. It must have its own explicit opt-in,
review record, evidence schema, and cleanup state. It must never be classified as
`quota-exhaustion`, share quota-exhaustion success evidence, or advance quota incident gates.

The workflow is allowed only against canonical `staging.token.place`, using HTTPS and exact
`GET` paths `/` and `/api/v1/meta`. Redirects must not be followed and are failures. Separate
control observations must prove exact `GET /livez` and `GET /healthz` responses remain `200`.
Production hosts, host aliases, query strings, fragments, alternate ports, and additional paths
are prohibited.

The workflow may observe an already configured, time-bounded rule; it must not create, edit,
enable, broaden, or delete that rule itself. Before any emulation observation, an independently
authorized operator must attest that the pre-existing rule or configuration:

- identifies only canonical `staging.token.place` and the two exact target paths;
- returns a static `429` without depending on a request counter;
- excludes `/livez`, `/healthz`, production, host wildcards, and path prefixes; and
- has named ownership, an expiry, and exact removal coordinates.

Missing, stale, unverifiable, or overly broad scope fails closed before requests are made. After
the evidence is reviewed, the authorized owner must remove the rule immediately. The run remains
failed and cleanup remains pending until an independent read-back proves that exact rule is absent
and the four routes have returned to `200/200/200/200` without redirects.

There must be **no** Deployment, image, replica, ServiceMonitor, Probe, registry, Kubernetes
resource, or data-plane mutation. The workflow must not generate load, attempt to exhaust a
budget, infer counter behavior, or reuse a marker. The default quota-exhaustion runner continues
to require its ordinary healthy `200/200/200/200` baseline; that baseline and its
`baseline-drift` failure must not be weakened, bypassed, or reclassified to accommodate static
emulation.

## Fail-closed observation and evidence

The only successful emulation observation is the exact tuple `429/429/200/200`, in target order
root, metadata, livez, and healthz, followed by independently proven cleanup and the exact healthy
tuple `200/200/200/200`. Any unexpected status, redirect, transport or TLS error, timeout, stale
attestation or observation, broad rule scope, host/path mismatch, or inability to prove cleanup
terminates the run as failed. Partial results are never success, and retries must not turn the
workflow into traffic stimulus.

Retained evidence is privacy-safe and bounded to:

- UTC start and finish timestamps and each route observation timestamp;
- route labels and numeric statuses before, during, and after emulation;
- a rule-scope attestation and its cryptographic hash;
- a cleanup attestation, independent absence/read-back result, and their hashes; and
- a workflow/version hash and final classification.

Evidence must contain no tokens, cookies, credentials, caller identity, query strings, response
bodies, request IDs, source addresses, or sensitive headers. The observer must not persist full
request or response headers. Evidence freshness limits and the attesting reviewer identities must
be defined during implementation review; absent or expired evidence fails closed.

## Future implementation plan

1. Specify a standalone command or manually dispatched workflow named
   `static-429-boundary-emulation`; do not add it to the incident drill runner.
2. Define a strict, versioned input/evidence schema with canonical-host and exact-path allowlists,
   redirect rejection, bounded sequential observations, freshness checks, and safe hashing.
3. Require two explicit inputs: approval to observe the pre-existing staging rule and an
   independent rule-scope attestation. Keep rule creation and removal outside the observer.
4. Observe the two controls separately from the target routes, emit only the privacy-safe fields
   above, and refuse to label the result quota exhaustion or rate-limit validation.
5. Model cleanup as a required terminal gate: accept an independently produced removal
   attestation, verify absence plus the restored healthy tuple, and leave failures visibly pending.
6. Obtain independent security and operations review of the implementation, tests, evidence
   schema, request budget, freshness window, and provider-specific read-back procedure.

Required unit tests must cover staging acceptance; every production/alias/port rejection; exact
path and method enforcement; redirect rejection; target and control status mismatches; transport,
TLS, and timeout failures; stale or malformed attestations; broad host/path rule scopes; evidence
redaction; deterministic hashes; no response-body/header retention; zero-retry bounded behavior;
cleanup absence and restored-baseline proof; pending cleanup on ambiguity; and explicit separation
from every quota-exhaustion parser, plan, journal, stage, and success classification. Static tests
must also prove that the implementation contains no Kubernetes, registry, Cloudflare mutation, or
Deployment/Probe/ServiceMonitor mutation path.

## Authorization boundary

Merging a future implementation, generating offline fixtures, or reviewing a pre-existing rule
does not authorize live observation. Any later live rehearsal requires a new, run-specific written
authorization from the staging service owner and the boundary-rule owner. It must name the
canonical host, exact paths, rule identifier and scope hash, observation window, evidence location,
reviewers, removal owner, removal deadline, and abort/cleanup procedure. Production cannot be
authorized under this design. The rule must be installed through a separately reviewed process
before the workflow starts and removed immediately after evidence review; the observer itself has
no mutation authority.
