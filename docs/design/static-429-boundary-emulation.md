---
personas:
  - software
---

# Static 429 Boundary Emulation (Design Only, Not Yet Implemented)

## Status and purpose

This document proposes a future, independently reviewed **static 429 boundary emulation** workflow.
It is documentation only: this change does not provide a command, create or alter a WAF rule, or
authorize a rehearsal. The workflow would observe a pre-existing, narrowly scoped staging boundary
configuration and then require its removal. It is not a mode or stage of
`tokenplace_incident_drill.py` and must not be added to its quota-exhaustion lifecycle.

Production is prohibited. The only permitted origin is the canonical
`https://staging.token.place`, with exact observation paths `/`, `/api/v1/meta`, `/livez`, and
`/healthz`. Redirects are never followed or accepted.

## Historical context and limits of the evidence

A prior bounded quota-stimulus executor existed at commit
`7c48c8184b69ee190863d29281ed97317d830474` and was removed by current commit
`d43154c670299baa3c1e43357f53ac2c8ece3cb0`. It must not be restored as part of this design or its
future implementation.

In the temporary WAF custom-rule experiment, `/` and `/api/v1/meta` returned HTTP 429 while
`/livez` and `/healthz` returned HTTP 200. The prior executor correctly failed closed with
`baseline-drift`: its ordinary healthy baseline requires `200/200/200/200` before generating any
stimulus. Marker cleanup completed, no Deployment mutation occurred, and the WAF custom rule was
deleted.

That result demonstrates only static response behavior at a boundary. It is **not** evidence of
genuine quota exhaustion, consumption of a quota window, counter increments, counter sharing,
reset timing, caller bucketing, or any other rate-limit-counter behavior.

## Classification and non-goals

The proposed lifecycle name is `static-429-boundary-emulation`. Its classification and retained
evidence must use that exact name. It requires an explicit opt-in specific to this lifecycle; quota
or incident-drill acknowledgements cannot substitute for it.

The workflow would:

- validate and observe a pre-existing boundary rule or configuration;
- prove the two selected public routes return 429 while both health controls remain 200; and
- prove the reviewed boundary configuration was removed immediately after evidence review.

It would not:

- send traffic intended to consume a quota or advance a counter;
- diagnose, claim, or recover from genuine quota exhaustion;
- validate rate, burst, window, reset, identity, or distributed-counter semantics; or
- mutate a Deployment, image, replica count, ServiceMonitor, Probe, registry artifact, Kubernetes
  resource, application data plane, or application state.

The ordinary quota-exhaustion runner continues to require its healthy `200/200/200/200` baseline.
That baseline and its `baseline-drift` failure must not be weakened, bypassed, reclassified, or
special-cased to accommodate static emulation.

## Proposed contract

### Authorization and preconditions

A future tool must default to a non-networked plan/validation mode. Live observation would require
all of the following:

1. An independently reviewed plan naming lifecycle `static-429-boundary-emulation`, environment
   `staging`, host `staging.token.place`, and only the four exact paths above.
2. A distinct, single-use opt-in for observing the pre-existing rule. General staging access,
   incident-response approval, or quota-rehearsal approval is insufficient.
3. A separate human authorization for that live rehearsal, scoped to a named maintenance window,
   reviewer, evidence destination, and exact rule identifier and digest. Documentation or tool
   availability alone grants no authority to create, enable, change, or rehearse a live rule.
4. Attestation, obtained before any HTTP observation, that the rule/configuration already exists;
   matches only the canonical staging hostname and exact `/` and `/api/v1/meta` paths; returns only
   static HTTP 429; excludes `/livez` and `/healthz`; cannot match production or another hostname;
   and has a reviewed removal owner and procedure.
5. Freshness bounds for the plan, authorization, rule-scope attestation, and observation window.
   The future implementation must define short fixed maxima and reject missing or stale values.

The workflow is an observer, not a rule manager. It must never create, widen, enable, or edit the
boundary configuration. Removal remains an operator action through a separately controlled system.

### Observation sequence

After validating all preconditions, the future workflow would perform one bounded observation of
each exact path with redirects disabled and without credentials, cookies, query strings, or request
bodies. The required tuple is:

| Exact path | Required status | Role |
| --- | ---: | --- |
| `/` | 429 | emulated boundary target |
| `/api/v1/meta` | 429 | emulated boundary target |
| `/livez` | 200 | independent liveness control |
| `/healthz` | 200 | independent health control |

Both controls are mandatory and separate; success on one cannot stand in for the other. The
observation must verify the final URL remains the exact requested HTTPS URL on
`staging.token.place`. No other route may be sampled.

Evidence review must be followed immediately by removal of the pre-existing configuration. A fresh
cleanup attestation must bind the removed rule identifier and digest to the same run. A subsequent
read-only scope check must prove the rule is absent; another 429 response is not proof of cleanup.
The run remains failed and incomplete if absence cannot be established.

### Fail-closed behavior

Stop without retrying or broadening scope on any unexpected status, redirect, TLS/DNS/transport
error, destination drift, stale or mismatched evidence, rule that is absent before observation,
rule scope broader than the two target routes, unhealthy control, production reference, or
unproven cleanup. Failure must never trigger changes to Kubernetes or the application data plane.
If cleanup cannot be proved, retain a failed cleanup-required state and escalate to the authorized
rule owner; never report success based only on an attempted deletion.

## Evidence and privacy

Retained evidence is limited to:

- lifecycle classification, run identifier, UTC observation timestamps, and the four route/status
  pairs;
- a rule-scope attestation naming only the reviewed rule identifier, canonical host, exact path
  set, static action, reviewer, timestamp, and a SHA-256 digest of the reviewed configuration;
- a cleanup attestation naming the rule identifier, removal and verification timestamps, verifier,
  absence result, and hashes binding it to the plan and scope attestation; and
- deterministic SHA-256 hashes of the plan and evidence records.

Do not retain tokens, credentials, cookies, request or response bodies, sensitive headers, caller
identities, request identifiers, query strings, raw provider exports, or unrelated configuration.
Evidence must explicitly say that static boundary emulation does not establish quota exhaustion or
rate-counter behavior.

## Future implementation and review plan

Any implementation must arrive in a separate pull request and receive independent security and
operations review. It should be a standalone tool/workflow with its own schema, lifecycle, evidence
directory, command surface, and documentation—not an extension of
`tokenplace_incident_drill.py`. The implementation should proceed in this order:

1. Define a strict, versioned plan and evidence schema with exact-host/path allowlists, freshness
   limits, immutable digests, explicit staging-only classification, and no mutation commands.
2. Implement offline validation first, then a redirect-disabled, bounded read-only observer. Keep
   rule creation/edit/removal outside the tool and accept only attestations from the independently
   controlled boundary system.
3. Add durable failure and cleanup-required states so interruption cannot be interpreted as
   success, and require a fresh post-removal absence attestation to complete a run.
4. Document operator review, evidence retention, escalation, and the explicit live-rehearsal
   authorization record. Rehearsal remains prohibited until that implementation PR is merged and a
   separate named approver authorizes one staging maintenance window.

Required unit tests must prove rejection of production and noncanonical hosts; extra, reordered,
encoded, normalized, query-bearing, or redirected paths; broad or stale rule attestations; every
unexpected status; either health control not returning 200; transport failures; stale/mismatched
hashes and timestamps; credentials or forbidden evidence fields; missing explicit opt-in; reuse of
quota-drill authorization; cleanup attempts without proven absence; and any plan containing a
Deployment, image, replica, ServiceMonitor, Probe, registry, Kubernetes, rule-mutation, or
data-plane mutation action. Positive tests must cover only the exact `429/429/200/200` tuple and a
fresh, hash-bound cleanup attestation. Integration tests must use local fakes and must verify that
redirects are disabled and no request is sent until the pre-existing scope attestation passes.
