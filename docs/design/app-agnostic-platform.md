---
personas:
  - software
---

# App-Agnostic Sugarkube Platform Design (Forward-Looking, Not Yet Implemented)

## Overview

Sugarkube's generic deployment surface (`scripts/app_config.py`, the generic `just app-*` recipes,
`docs/app_deployment_contract.md`) already lets an app onboard by adding a small config file and a
runbook. But several of the engines that sit *behind* that generic surface — Helm lifecycle
verification, blackbox probe inventory, dashboard validation, and release-evidence/rollback policy —
still hardcode DSPACE, token.place, danielsmith, and jobbot3000 by name. This document is a design for
closing that gap: moving app-specific data out of generic engines and into app-owned configuration,
while keeping genuinely specialized behavior behind an explicit adapter interface rather than forcing
it into an inappropriate universal abstraction.

**This document proposes nothing that is implemented in this PR.** It is documentation only: no
script, `justfile`, or manifest changes accompany it. It exists so the migration described here can be
reviewed, sequenced, and executed incrementally in later PRs.

## Problem statement

Four applications are onboarded today, and each new one currently requires touching generic Python and
shell code, not just app-owned configuration:

- `scripts/app_config.py:16` hardcodes `EXAMPLE_FALLBACK_APPS = {"danielsmith", "dspace", "jobbot3000", "tokenplace"}` to gate which apps get a bundled example-config fallback.
- `scripts/observability_helm.sh`'s `verify_dspace_targets()` (lines 86-207) and its literal `kubectl -n dspace get servicemonitor dspace ...` calls (lines 236-241) assume DSPACE is the only app with a `ServiceMonitor` worth verifying.
- `scripts/verify_blackbox_prometheus.py:8-25` hardcodes a 16-entry `EXPECTED` dict mapping every current probe name to `(app, route)` — a fifth app's probes require editing this Python literal by hand.
- `scripts/validate_observability_dashboard.py:15-33` hardcodes DSPACE metric names (`REQUIRED_METRICS`) and a 4-app regex (`BLACKBOX_JOB_MATCHER`) into the shared dashboard validator.
- The `justfile` has DSPACE-only policy inlined directly into the otherwise-generic `app-deploy`/`app-redeploy` recipes (`if [ "${SUGARKUBE_APP}" = dspace ]` blocks), plus a DSPACE-only `dspace-manifest-rollback` recipe with no generic equivalent.
- `scripts/dspace_release_manifest.py` and `scripts/dspace_manifest_rollback.py` implement DSPACE-specific release-evidence and rollback policy, with `dspace`/`chat` hardcoded into validation logic.

None of this is a defect by itself — DSPACE was the first app, and the fastest path to a working
system was to write DSPACE-specific verification first and generalize later. jobbot3000, notably,
already onboarded through the generic `app-*` path with zero `justfile` matches — it is the existing
proof that the generic surface works when an app doesn't need anything beyond it.

## Goals

- Let a new application onboard by adding app-owned configuration, documentation, fixtures, and tests
  — not by editing generic Python, shell, or `just` dispatch code.
- Keep every migration step backward compatible: existing apps keep working at every intermediate
  step, and compatibility shims are allowed to exist temporarily.
- Preserve genuinely specialized behavior (DSPACE release evidence, rollback) as an explicit,
  well-defined capability rather than deleting it or forcing it into a shape it doesn't fit.

## Non-goals

- This document does not implement any of the migration steps below.
- This document does not remove any existing compatibility recipe or app-specific functionality.
- This document does not create `platform/apps/<app>/`, `config/apps/<app>/`, or any other new
  source-of-truth directory — see [Proposed directory layout](#proposed-directory-layout) for why that
  remains an open decision rather than a decision made here.
- This document does not attempt a big-bang migration; see [Migration inventory and phases](#migration-inventory-and-phases).

## Design principles

1. **Generic core logic operates on validated declarative app descriptions.** Verification, dashboard
   validation, and lifecycle scripts should read an app's identity, routes, and expectations from data,
   not from `if app == "dspace"` branches.
2. **App-specific data lives in app-owned configuration or documentation.** `docs/apps/`,
   `docs/examples/apps/`, and app repositories are the right home for names, routes, and metric lists —
   not Python dict literals inside generic verification scripts.
3. **Specialized behavior uses explicit capabilities/adapters.** When an app genuinely needs something
   no other app needs (DSPACE's release-evidence/rollback flow), that behavior should be reachable
   through a declared capability the generic engine checks for, not a silent per-app branch.
4. **No arbitrary shell or executable code in data files.** App descriptors are declarative data
   (YAML/JSON/env), never scripts the generic engine `eval`s or `source`s.
5. **Schemas fail closed and produce actionable validation errors.** An app descriptor that's missing a
   required field should fail with a specific, fixable error — mirroring `scripts/app_config.py`'s
   existing `REQUIRED_KEYS` validation, not a generic engine that silently skips the app.
6. **Secrets remain outside Git.** No migration step changes this; app descriptors reference secret
   names/paths, never secret values, matching the existing `SUGARKUBE_*` convention.
7. **Migration is incremental and backward compatible.** Every phase in this document can ship
   independently, and existing apps must not regress between phases.
8. **Generated artifacts are distinguishable from their source of truth.** If a migration step
   generates, say, Probe YAML from an app descriptor, the generated file must be clearly marked
   generated (header comment, separate directory, or CI-enforced regeneration check) so nobody hand-
   edits it and has the edit silently discarded.

## Ownership boundaries

Extending the split already established in `docs/observability-design.md` §3:

| Owner | Responsibility |
| --- | --- |
| Generic Sugarkube lifecycle engine (`scripts/app_config.py`, generic `just app-*` recipes) | Reading app descriptors, resolving environment/tag/values precedence, running deploy/redeploy/promote against the cluster. Already mostly generic today. |
| Generic Sugarkube observability engine (`scripts/observability_helm.sh`, `verify_blackbox_prometheus.py`, `validate_observability_dashboard.py`) | Reading declared probe/metric expectations from app descriptors instead of hardcoded literals; verifying what's declared, for any app. |
| Per-application repository configuration | The app's `Dockerfile`, Helm chart, image/chart publishing workflows — unchanged by this design. |
| Per-application Sugarkube descriptor (`docs/apps/`, `docs/examples/apps/`, or a future dedicated location — see below) | App identity, routes, probes, expected metrics, dashboard/alert metadata, declared capabilities. |
| Per-environment overrides (`clusters/<env>/`) | Environment-specific values overlays and, where relevant, per-env probe/observability config — unchanged in shape, but should be generated from or validated against the same descriptor. |
| Application repositories | App-owned runbooks, release notes, and any capability implementation the app declares (e.g., a DSPACE-style release-evidence tool). |
| Optional specialized adapters | Capability-specific logic (release evidence, rollback, synthetic checks) that only some apps need, invoked through a declared-capability interface rather than a name check. |

## Proposed app contract

A generic application descriptor should carry enough data for the generic engines to verify an app
without any app-specific code. Building on the existing shape of `docs/examples/apps/*.env`
(`SUGARKUBE_APP`, `SUGARKUBE_RELEASE`, `SUGARKUBE_NAMESPACE`, `SUGARKUBE_CHART`, `SUGARKUBE_VERSION_FILE`,
`SUGARKUBE_VALUES_*`, `SUGARKUBE_VERIFY_PATHS`, ...), the descriptor should additionally cover:

- **Identity and release coordinates**: app slug, namespace, Helm release name, chart reference, and
  version pin — already covered by today's `.env` shape.
- **Image policy**: image repository and the tag/version policy (immutable branch-SHA tags today, per
  `scripts/app_config.py`'s `resolve_tag()`).
- **Ordered values/configuration sources**: the existing comma-separated values chain per environment.
- **Public host and verification routes**: host key plus HTTP paths to check post-rollout — already
  covered by `SUGARKUBE_VERIFY_PATHS`.
- **Readiness/liveness behavior**: which paths are liveness vs. readiness vs. general content checks.
- **CORS checks**, where applicable (already exercised by the generic `app-cors-verify` recipe for
  some apps).
- **Metrics and `ServiceMonitor` expectations**: whether the app exposes `/metrics`, the namespace/name
  of its `ServiceMonitor`, and whether it's bearer-token authenticated — generalizing what
  `verify_dspace_targets()` currently hardcodes.
- **Blackbox probes**: a list of `{route, url_or_path, module, interval, criticality}` entries per
  environment — generalizing the `EXPECTED` dict in `verify_blackbox_prometheus.py` and the literal
  Probe YAML in `clusters/staging/observability/probes/public-apps.yaml`.
- **Expected metric families**: the app-owned metric names a dashboard/alert should be able to rely on
  — generalizing `REQUIRED_METRICS` in `validate_observability_dashboard.py`.
- **Dashboard and alert/runbook metadata**: which dashboard panels and alert names belong to this app,
  and where its runbook lives.
- **Optional declared capabilities**: e.g. `release_evidence`, `manifest_rollback`, `synthetic_check`,
  each naming an adapter the generic engine can look up rather than hardcoding.

## Proposed directory layout

Prefer extending the directories that already exist over inventing a parallel hierarchy:

- `docs/apps/<app>.md` already holds the human-readable runbook.
- `docs/examples/apps/<app>.env` already holds a machine-readable, generic-recipe-consumable
  descriptor, gated today by `EXAMPLE_FALLBACK_APPS`.
- `apps/<app>.env` is already the documented (if mostly unused today — only `apps/tokenplace-relay/`
  has real content) location for a local, non-example app config per `scripts/app_config.py`'s
  `iter_config_candidates()`.

Extending `docs/examples/apps/*.env` (and its private counterpart, `apps/<app>.env`) with the
additional fields above is the lower-friction option: no new directory, and every existing app
already has a file there to extend incrementally, field by field.

The alternative — a dedicated source-of-truth directory such as `platform/apps/<app>/` or
`config/apps/<app>/` holding a structured descriptor (YAML/JSON) per app, separate from the `.env`
files — would give the descriptor room to grow beyond flat key-value pairs (nested probe lists,
per-route metadata) without overloading the `.env` format. That's a real advantage once the descriptor
needs probe lists or capability declarations, which don't fit a flat `KEY=value` file cleanly.

**This is presented as a decision to be made, not made here.** Weighing it requires seeing how far the
`.env` format can be stretched (e.g. `SUGARKUBE_BLACKBOX_PROBES` as a structured but flat-encoded
value) versus introducing a new directory and a second file operators need to know about. Neither
directory is created in this PR.

## Migration inventory and phases

### Classification

1. **Declarative app data that should move first** (low risk, no behavior change): the 16-entry probe
   `EXPECTED` dict in `verify_blackbox_prometheus.py`; the `REQUIRED_METRICS`/`BLACKBOX_JOB_MATCHER`
   literals in `validate_observability_dashboard.py`; `EXAMPLE_FALLBACK_APPS` in `app_config.py`.
2. **Generic engine behavior that should consume the new contract**: `verify_dspace_targets()`
   generalizing to "verify every app descriptor that declares a `ServiceMonitor`"; the blackbox/
   dashboard verification scripts reading probe/metric expectations from descriptors instead of
   literals.
3. **Compatibility shims to deprecate later, not now**: the per-app `justfile` wrapper recipes
   (`dspace-oci-deploy`, `tokenplace-oci-deploy`, `danielsmith-oci-deploy`, and their siblings) that
   already just delegate to the generic `app-deploy app=<name>` — these can stay until callers
   (scripts, CI, muscle memory) migrate off them.
4. **Legitimate specialized behavior that should become an adapter**: DSPACE's release-evidence
   reservation/finalization (`scripts/dspace_release_manifest.py`) and fail-closed rollback
   (`scripts/dspace_manifest_rollback.py`). The rollback script's existing
   `verifier_capabilities()`/`REQUIRED_CAPABILITIES` pattern (lines 87-121) is the closest existing
   precedent for a capability-negotiation interface in this repo — generalizing it means
   parameterizing `release`/`namespace`/app-name and the required-journey list (currently hardcoded to
   `/chat`) instead of assuming DSPACE.

### Incremental plan

1. **Inventory current behavior and lock it down with tests.** Before moving anything, add/extend
   tests (following `tests/test_app_config.py`'s existing "custom app via temp config dir" pattern) that
   pin today's DSPACE-hardcoded behavior, so a later refactor has a regression net.
2. **Define and validate the app descriptor schema.** Fields from [Proposed app contract](#proposed-app-contract);
   fail-closed validation with actionable errors, matching `app_config.py`'s existing `REQUIRED_KEYS`
   style.
3. **Migrate blackbox probe inventory and verification** off the `EXPECTED` literal in
   `verify_blackbox_prometheus.py` onto descriptor-sourced expectations, keeping the same 16-probe
   staging outcome unchanged.
4. **Make metrics-target verification declarative** rather than DSPACE-specific: generalize
   `verify_dspace_targets()` to iterate over any app descriptor declaring a `ServiceMonitor`.
5. **Make dashboard validation data-driven or app-owned**: replace `REQUIRED_METRICS`/
   `BLACKBOX_JOB_MATCHER` literals with descriptor-sourced expectations.
6. **Thin or remove app-specific `just` wrappers** only after their callers (scripts, CI, docs) have
   migrated to the generic `app-*` recipes with `app=<name>`.
7. **Place DSPACE release evidence and rollback behind a declared capability**, generalizing
   `verifier_capabilities()`/`REQUIRED_CAPABILITIES` so a future app could declare the same capability
   without editing `dspace_manifest_rollback.py` itself.
8. **Delete obsolete hardcoding only after parity and migration tests pass** — never as part of the
   same change that introduces the new data-driven path.

### Acceptance test

A strong eventual acceptance test for this migration: **onboarding a simple fifth application requires
only app-owned configuration, documentation, fixtures/tests, and environment selection — no edits to
generic Python, shell, or `just` dispatch code.** jobbot3000 already satisfies this for the deploy path
today (zero `justfile` matches); the goal is for the observability verification scripts to reach the
same bar.

## Backward compatibility

Every phase above must leave existing apps (DSPACE, token.place, danielsmith, jobbot3000) working
identically at each intermediate commit. Compatibility shims (the `justfile` wrappers, the `.env`
fallback mechanism) are explicitly allowed to persist across multiple phases; nothing in this design
requires removing them on a deadline.

## Testing

Each migration phase should extend, not replace, the existing test suite: `tests/test_app_config.py`'s
"custom app" pattern is the template for proving new-app-without-code-changes already works partially
today; the blackbox/dashboard verification scripts should gain equivalent "declare a synthetic 5th app
via descriptor, verify it" tests before their hardcoded literals are removed.

## Security

No migration step changes secret handling: descriptors reference secret names (e.g. a `ServiceMonitor`
bearer-token Secret name), never secret values, matching the existing `SUGARKUBE_*` convention and the
`scan-secrets.py` gate already run on every PR. Declarative descriptors must remain data only — no
capability may be satisfied by embedding arbitrary shell/code in a descriptor file (Design principle 4).

## Bounded label/cardinality concerns

Descriptor-driven probe and metric expectations must preserve the same bounded-label discipline already
required by `docs/observability-design.md` §5 (bounded routes, status classes, outcomes) — a generic
descriptor schema must not make it easier to accidentally declare an unbounded label (e.g. a raw URL as
a probe "route") than today's hand-written literals do.

## Deterministic ordering

Where a migration step generates configuration from descriptors (e.g. probe YAML, dashboard job
regexes), output ordering must be deterministic (e.g. sorted by app then route) so diffs stay reviewable
and repeated runs produce byte-identical output, matching the existing dashboard-render byte-equality
check in `validate_observability_dashboard.py`.

## Failure behavior

A malformed or incomplete app descriptor must fail closed with an actionable error at validation time,
not silently skip the app's verification or probes. This mirrors `app_config.py`'s existing behavior
for missing required keys and should extend to the new descriptor fields.

## Decisions recorded in this document

- PagerDuty/Healthchecks.io alerting strategy is out of scope here — see
  [`docs/observability-alerting.md`](../observability-alerting.md).
- Extend existing `docs/examples/apps/`/`apps/<app>.env` conventions is the default-preferred direction
  over inventing a new source-of-truth directory, but the final choice is deferred (see
  [Proposed directory layout](#proposed-directory-layout)).
- DSPACE release evidence/rollback should become an explicit capability/adapter, not a universal
  abstraction every app must implement.

## Open questions

- Can the flat `.env` format cleanly represent a list of blackbox probes and their metadata, or does
  that field alone justify a structured (YAML/JSON) descriptor?
- Should the capability-declaration mechanism be a simple string list (`SUGARKUBE_CAPABILITIES=release_evidence,manifest_rollback`)
  or a more structured per-capability config block?
- How should descriptor validation errors surface in CI versus at `just app-*` invocation time?
- Once jobbot3000 or a future app wants `ServiceMonitor` scraping, should it reuse DSPACE's exact
  bearer-token pattern, or does the descriptor need to support multiple auth strategies from the start?
