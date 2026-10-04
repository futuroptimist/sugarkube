---
personas:
  - software
---

# Unmatched-path edge evaluation

## Decision: no enforcement rule justified

This is the repository-only Step 15a evaluation for
[issue #2780](https://github.com/futuroptimist/sugarkube/issues/2780), based on Sugarkube
`2c3276d6b9f001eef8cb588a7086e0dab67d8730`. Leave the issue open. The replay below bounds
an illustrative candidate's matched load but disproves its safety for legitimate missing-page
traffic. It does not justify a production rule, establish a live baseline, or identify an actor
or intent. No edge, ingress, application, quota, memory, or observer settings change.

## Source evidence and prerequisite

- The [ingress template](../../apps/tokenplace-relay/templates/ingress.yaml) forwards the
  configured prefix to the relay. It has no application route classifier.
  [Cloudflare routes are external to Helm](../apps/tokenplace-relay.md#cloudflare-tunnel-guidance).
- The [probe inventory](../../config/observability/tokenplace-incident-probes.json) contains
  only root, metadata, readiness, and liveness GET requests. It is not a browser/API allowlist.
- Application source was reviewed at token.place commit
  `4fdc779858140608edce8adfc49d6a21243fa781`. Its
  [incident record](https://github.com/futuroptimist/token.place/blob/4fdc779858140608edce8adfc49d6a21243fa781/outages/2026-09-02-production-relay-metrics-cardinality-oom.md)
  records the bounded-cardinality backport, recovery rollout and restored authenticated scraping,
  and links completed trackers #1765, #1766, #2774 and #2775. This establishes the recorded
  prerequisite, not a fresh runtime verification or proof of the undocumented 24-hour stability gate.
- In that commit's
  [relay source](https://github.com/futuroptimist/token.place/blob/4fdc779858140608edce8adfc49d6a21243fa781/relay.py),
  `_normalise_http_route` returns finite labels and metrics use a dedicated registry.
  **`other` is not an unmatched-route classifier**: root, metadata, version and static routes
  also fall into it. Blocking that label would harm legitimate traffic. No raw-path labels
  should be added to distinguish them.

## Legitimate route and method baseline

This is a source-derived compatibility inventory, not observed traffic rates. Literal route
templates below are public source contracts, never retained request paths. Automatic HEAD and
OPTIONS behavior must be preserved alongside each registered method. A 404, 405, authentication
failure or application validation error remains the application's response, not proof of abuse.

| Finite class | Source contract examples | Methods to preserve |
| --- | --- | --- |
| browser | Root and static asset route templates | GET, HEAD, OPTIONS |
| public | API-v1 metadata, version, models, public key, community information | GET, HEAD, OPTIONS; registered POST operations |
| health | Liveness, readiness and API health | GET, HEAD, OPTIONS |
| metrics | Authenticated metrics; authentication rejection remains intact | GET, HEAD, OPTIONS |
| e2ee | API-v1 relay requests, responses, retrieval, cancellation and progress | POST, OPTIONS |
| compute | API-v1 server registration, unregister, poll and control; next server and availability | POST, GET, HEAD, OPTIONS as registered |
| unmatched | Ordinary missing pages, stale bookmarks and random requests | All methods remain application-owned |
| unknown | New routes, ambiguous normalization and classification drift | Forward; require review before enforcement |

The local model tests all six preserved classes against GET, HEAD, OPTIONS, POST, PUT, PATCH,
DELETE and `other`, including methods the application may reject. Passing this matrix only proves
that the model forwards these categories. It does not claim full application routing, asset
delivery, E2EE execution or a verified Cloudflare expression. API-v1 contracts also include
blueprint routes and aliases; an edge allowlist needs the complete immutable router inventory,
normalization parity and future-route review, not just these examples.

## Candidates and deterministic replay

| Candidate | Evaluation |
| --- | --- |
| Global host rate limit | Reject: shared exhaustion can deny assets, health, metrics and compute traffic. |
| Per-client limit | Reject for this evaluation: proxy identity and legitimate shared-client rates are unqualified; no client identity is retained. |
| Bot score or challenge | Reject: no reviewed finite score threshold or browser/API compatibility evidence; challenges can break non-browser E2EE and compute clients. |
| Path length, character pattern or prefix denylist | Reject: no source contract establishes a safe cutoff; random traffic can mimic legitimate shape. |
| Shared unmatched budget | Evaluate below using an ideal classifier; reject because ordinary 404 requests share the budget. |

The finite hypothetical condition is `category == unmatched`, for all eight method categories,
with one shared budget of 100 forwarded requests per fixed 60-second window. Preserved and unknown
categories bypass it. This is an intentionally optimistic model: a trustworthy pre-origin
unmatched classifier is not available in the reviewed ingress. A response-based 404 limiter still
incurs the initial origin work. The budget is illustrative, not a measured capacity recommendation.
Fixed windows allow up to 200 requests across a boundary; this is not a sliding-window guarantee.
Traffic using preserved or unknown categories is outside this bound.

Run from the repository root, without network access:

```sh
python3 scripts/tokenplace_edge_replay.py
pytest -q tests/test_tokenplace_edge_replay.py
```

The fixed seed is 2780. Three windows each contain 1,000 synthetic unmatched requests with
randomized method categories, then a shuffled 48-cell preserved matrix, three legitimate
missing-page requests and one unknown request. No path strings, identities or payloads are inputs.
This is category-level replay, **not raw randomized-path routing replay**.

| Aggregate | Result |
| --- | --- |
| Unmatched attempts | 3,000 |
| Candidate forwarded | 300 (90% reduction for the modeled matched traffic) |
| Edge disabled forwarded | 3,000 |
| Preserved matrix forwarded | 144 / 144 |
| Legitimate missing-page requests blocked | 9 / 9 (100% false positives in this adversarial ordering) |
| Unknown requests forwarded | 3 / 3 |

The collision is sufficient to reject the candidate even with perfect route classification.
It is not an estimate of production false-positive prevalence. Application 404 correctness and
availability must not depend on this candidate. Disabling it removes the modeled traffic bound;
bounded metric cardinality is a separate application property.

## Metrics safety with edge disabled

The application tests at the pinned source run through Flask's in-process test client, with no
edge control. `tests/unit/test_relay_logging_and_metrics.py` covers unmatched paths and query
redaction, bounded custom method labels, dedicated-registry export, sensitive-value exclusion,
metrics authentication before collection, and compute control metrics. Run it alongside
`tests/unit/test_rate_limit.py`, `tests/unit/test_public_quota_metrics.py` and
`tests/unit/test_e2ee_relay_invariant.py` in that checkout with its focused verification dependencies.
These are application regressions, not claims that the category model implements real metrics.
The PR records their exact local results. Do not run a release gate against a remote relay as part
of this evaluation. Requalify the exact future deployment image before any live enforcement.

## Gates for any future proposal

These are proposed minimum review gates, not authorization or a claim that a rule meets them:

- **False positives:** zero blocks/challenges of preserved or ordinary legitimate missing-page
  requests in the complete source-derived replay matrix, including invalid methods, escaped
  forms, normalization ambiguity and a newly introduced route. Unknown classification forwards.
  Any regression rejects the candidate; the evaluated candidate fails this gate.
- **Observation:** after separate environment-specific approval, at least 24 hours and 10,000
  legitimate requests in aggregate, with coverage of every preserved class. Report per-class
  attempts, would-block counts and status classes only. Missing class coverage or unavailable
  false-positive ground truth prevents rollout; elapsed time alone cannot qualify a rule.
- **Rollout:** first offline replay, then a separately approved staging-only 30-minute window.
  Require zero legitimate false positives, at least 90% reduction of the explicitly matched
  synthetic workload, and no more than 10% increase in per-class error rate or latency over the
  reviewed baseline. For a zero-error baseline require zero new errors. Production requires
  a new approval, exact versioned expression, named owner and tested removal procedure; no
  production percentage or capacity value is justified here.
- **Rollback:** immediately disable the exact candidate on the first legitimate block/challenge,
  a health/authenticated-metrics/E2EE/compute failure, classification drift, loss of observations,
  or an error/latency threshold breach in two consecutive one-minute windows. Owner must be
  able to remove the rule within five minutes; otherwise do not start. After removal require
  the complete matrix to recover and 15 minutes within baseline thresholds. Leave application
  metrics and existing quota controls intact.

Only fixed aggregate counters leave the replay process. No observed paths, query strings,
credentials, payloads, request IDs, source identities or addresses are collected. Future evidence
needs its own reviewed retention/access/expiry contract; this evaluation creates no observer.

## Stronger-signal investigation: executable design specification

The follow-up keeps the enforcement objective open. It does not replace the rejected shared-budget
counterexample above. A trusted, specific attack signal could narrow the match, but neither the
provider capability nor its discrimination accuracy is established by repository evidence. This
section and `SignalCandidate` are an offline specification, not an edge expression or integration.
The original command output and original counterexample remain unchanged.

### Finite state and candidate decision

| Input | Closed vocabulary | Required state to enter the hypothetical budget |
| --- | --- | --- |
| Route category | The eight categories above | `unmatched` |
| Method | The eight methods above | Any; methods do not establish abuse |
| Capability | `available`, `unavailable`, `unknown` | `available` |
| Provenance | `verified`, `absent`, `spoofed`, `stale` | `verified` |
| Signal | `attack`, `none`, `unknown` | `attack` |
| Normalization | `equivalent`, `ambiguous`, `drift`, `unknown` | `equivalent` |

All five required states must hold simultaneously. Otherwise the request forwards without
consuming the hypothetical budget. Preserved and unknown routes always forward, even with an
attack signal. Eligible traffic uses the original shared 100-per-60-second fixed-window budget;
its boundary burst limitation remains unchanged. Disabled mode forwards every valid finite input.
Malformed fixture values reject the offline invocation with a fixed error; this is not a proposed
HTTP error response. In a future adapter, unknown external values must map to the bounded unknown
state and forward, never become a new label or an enforcement decision.

`verified` is only a fixture assertion here. The model performs no signature verification,
provider lookup, route matching, URL parsing or normalization. A request header cannot establish
trusted provenance. `equivalent` would require separately reviewed edge-to-origin normalization
and complete router parity. The model accepts no ground-truth abuse or legitimacy argument.

### Signals and missing qualifications

- A trusted provider attack-signature result is the conditional candidate. Each approved detection
  would map to one reviewed finite signal class. No particular detection ID, provider expression,
  score cutoff, entitlement or confidence level is selected. Benign-shaped random requests may
  carry no signature at all; therefore coverage of the original workload remains unknown.
- Automation alone is not abuse. API and compute clients are legitimately automated. Cloudflare's
  [bot-score documentation](https://developers.cloudflare.com/bots/concepts/bot-score/) describes
  low-score false positives from stripped User-Agent headers and restricts granular scores to
  Enterprise Bot Management. Current account capabilities have not been inspected.
- A source-defined protocol violation might protect a narrower subset, but a 404, 405, unusual
  method, long path or encoded path alone is not a reviewed forbidden contract.
- Positive client proof may preserve a recognized client. Absence of proof must not imply abuse.
  Adding authentication, challenges or client changes requires a separate product decision.
- Per-client bursts, path diversity and reputation introduce identity-linked state and shared-client
  collisions. They are not implemented or authorized by this finite aggregate specification.
  Hashing an identity does not make its cardinality finite or remove its privacy implications.
- User-Agent, referrer, fetch metadata, path entropy, global rate, 404 ratio and a trap-route hit
  are not sufficient standalone signals. Keep benign automation and stale bookmarks as explicit
  counterexamples. Response-based counting occurs after a response, so it cannot remove that
  request's initial origin work; see [rate-limit parameters](https://developers.cloudflare.com/waf/rate-limiting-rules/parameters/).

### Route and normalization test matrix

The executable test exhausts the hypothetical budget and checks all **9,216** combinations of
route, method, capability, provenance, signal and normalization. Only the eight method variants
of the fully qualified unmatched state may be denied. It also checks all combinations disabled,
untrusted/default inputs, invalid finite states, time reversal and fixed-window boundaries.

The following router/normalization cases are **required future differential fixtures, not executed
router tests in this PR**. Before a provider adapter is proposed, bind them to the full immutable
application router inventory and the documented edge behavior. Public source route templates and
synthetic inputs are allowed; observed request paths are not fixture material.

| Family | Required cases | Expected behavior |
| --- | --- | --- |
| Browser/public | Root, static assets, metadata, version, public key, model/community routes | Preserve registered methods plus automatic HEAD/OPTIONS and application-owned errors |
| Health/metrics | Liveness/readiness/API health; valid and invalid metrics authentication | Forward; preserve authentication and health semantics |
| E2EE/compute | API-v1 request/response/retrieval/cancel/progress; register/poll/control and aliases | Forward all registered methods and application-owned rejections |
| Legitimate missing | Stale bookmark, typo, missing asset, crawler, text/accessibility client | No block, including missing or misleading automation signals |
| Router drift | New route, alias, dynamic parameter, method mismatch, ambiguous classification | Forward unknowns; stop candidate qualification |
| Normalization | Escaped unreserved characters, repeated separators, dot segments, case, Unicode, encoded slash and double encoding | Do not guess equivalence; disagreement forwards and rejects qualification |

Cloudflare documents normalization before rule evaluation and optional normalization toward the
origin; see [URL normalization](https://developers.cloudflare.com/rules/normalization/).
A synthetic `equivalent` flag cannot establish this parity.

### Adversarial fixtures and decisive counterexamples

Run the stronger-signal replay without changing the original CLI:

```sh
python3 -c 'import json; from scripts.tokenplace_edge_replay import signal_replay; print(json.dumps(signal_replay(), sort_keys=True))'
pytest -q tests/test_tokenplace_edge_replay.py
```

Across three fixed windows the fixture contains 3,000 signaled attack attempts, 3,000 unsignaled
attack attempts, 144 preserved requests, nine ordinary missing-page requests without the signal,
nine legitimate missing-page requests incorrectly carrying the signal, and three unknown requests.
The population labels are synthetic accounting ground truth, never inputs to the matcher.

| Result | Count | Interpretation |
| --- | --- | --- |
| Signaled attacks forwarded | 300 / 3,000 | 90% reduction only for the hypothetical matched subset |
| Unsignaled attacks forwarded | 3,000 / 3,000 | No bound on traffic lacking the signal |
| All modeled attacks forwarded | 3,300 / 6,000 | 45% reduction for this chosen mixture, not an observed rate |
| Preserved requests forwarded | 144 / 144 | Finite model compatibility only |
| Ordinary missing pages forwarded | 9 / 9 | Improvement only when the signal is absent |
| Legitimate requests with false signals blocked | 9 / 9 | Counterexample still rejects safety qualification |
| Unknown requests forwarded | 3 / 3 | Unknowns cannot justify enforcement |
| Attacks forwarded with edge disabled | 6,000 / 6,000 | Metric safety must remain independently application-owned |

A provider with any legitimate overlap can still cause collateral blocking. A provider that misses
benign-shaped attacks may not meet the mitigation objective. No classifier accuracy, production
false-positive rate, live reduction or successful mitigation follows from assigning fixture flags.

### Acceptance gates and implementation boundary

Retain every gate above, including zero legitimate blocks, complete route coverage, separately
approved observations, rollback thresholds and application metrics tests with the edge disabled.
Additionally require a named source-backed signal, trusted provenance, confirmed capabilities,
normalization parity, and independent aggregate false-positive/coverage evidence. Missing evidence
is an explicit failed qualification gate, not a default assumption of safety. Include attack-first,
legitimate-first and interleaved sequences plus boundary bursts in any adapter qualification.
The fixed adversarial ordering here is sufficient to reject the candidate, not exhaustive load proof.

Export only fixed counters and approved finite states. Never retain observed paths, queries,
headers, cookies, tokens, credentials, payloads, fingerprints, addresses or identity hashes as
keys. Provider IDs need a reviewed finite mapping; arbitrary IDs collapse to unknown. The current
aggregate evidence schema is not extended by this work. No new observer, collection, identity store,
provider adapter, rule expression, client challenge or deployment is included. Keep #2780 open.

## Remaining acceptance gaps

The finite candidate and its counterexample are reviewable, privacy-safe and reproducible.
Model compatibility and matched-load bounds are demonstrated; **safe deployable matching,
complete router compatibility and real edge load reduction remain unproven**. No live baseline
was collected. Keep #2780 open and do not use a closing keyword in this evaluation PR.
No Cloudflare, Kubernetes, Helm, monitoring, staging or production action is part of this work.
