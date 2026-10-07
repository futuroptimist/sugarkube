# Disposable staging relay test lane (K243)

This is an **offline preparation**, not an installed service or permission to run traffic.
The [lane chart](../apps/tokenplace-test-lane/Chart.yaml) renders a separate relay in namespace
`tokenplace-k243`. It is deliberately absent from Flux and all cluster overlays. Deployment,
NetworkPolicy application, runner placement, compute allocation, traffic, and removal remain
explicitly operator-owned later actions. This work performs none of them.

## Fixed historical binding

The lane binds to token.place source
[`5e190f5c6ff66e9c05934a0e2ce2c1a440b9ea49`](https://github.com/futuroptimist/token.place/tree/5e190f5c6ff66e9c05934a0e2ce2c1a440b9ea49)
and image index
`ghcr.io/futuroptimist/tokenplace-relay@sha256:5d761cefc0495926b63da1e0a4119155a005e165e469da90e7f19be0f7fdff8e`.
There is one replica, `RELAY_WORKERS=1`, and memory request/limit **256Mi/256Mi**.
The digest is an index; later operator evidence must also record the resolved platform image and
verify its relationship to that index. These declarations do not attest to a running image.

The public limiter explicitly uses `memory://`, with `60/hour` and `1000/day` defaults.
The source's relay reservation store is also in process. A fresh, dedicated process gives a new
experiment baseline for this source/backend combination only. Current main uses different Valkey
semantics: a process restart does **not** establish fresh counters in shared storage. Rebinding the
source, storage, image, worker count, or quota settings needs another review.

Never reset counters or restart the serving relay. Never reuse a previous lane as a fresh baseline.
A unique `runId` labels each experiment; changing it requires a new Deployment because its selector
is immutable. Any worker replacement, pod replacement, restart, OOM, or identity drift invalidates
the experiment. `Recreate` avoids a rolling overlap; it does not make restarts acceptable evidence.

## Isolation and access

The Deployment and private ClusterIP Service are named `tokenplace-k243-relay`. Their namespace,
name label and run label differ from the serving relay. No Ingress, public route, load balancer,
autoscaler, runner, compute workload, Secret, persistent volume, or monitoring discovery is created.
The chart admits only `runId`; image, memory, replica, ingress and environment overrides are rejected.
It refuses a release namespace other than `tokenplace-k243`.

Three policies deny all ingress/egress in the lane, then allow only TCP 5010 from a runner in the
**same namespace** with both labels:

```yaml
app.kubernetes.io/name: tokenplace-k243-runner
sugarkube.dev/k243-run: <the reviewed runId>
```

The runner can reach only the matching relay pods. DNS and external egress are not allowed; the
operator must supply a private destination after reviewing the actual Service and CNI behavior.
No runner is provisioned here. Label selection cannot enforce exactly one runner or authenticate a
person: namespace write access and label assignment must be restricted to the designated operator.
Before any later traffic, that operator must verify exactly one authorized runner, enforced CNI
policies, no additive allow policies, no serving Service overlap, and no host-network or privileged
bypass. Kubernetes node/probe traffic and privileged administrators are outside the pod policy
boundary. Applying these policies to a reused namespace could disrupt unrelated pods; the namespace
must be new, dedicated, and empty before adoption.

No serving credentials, registration tokens, pull secrets, proxy trust, or configuration volumes
are copied. Service account token mounting and service-link environment injection are disabled.
Runtime writable configuration, logs and keys stay under bounded disposable `/tmp`; the root
filesystem is read-only. Any later private registry credentials, compute registration, telemetry
access or policy changes need a separately reviewed lane-only configuration. Do not silently borrow
serving credentials or widen these policies to make a test work.

The direct private path can qualify **relay-local behavior**. It cannot qualify the public edge,
CDN/WAF, public routing, trusted proxy identity, or production caller isolation. Forwarded identity
headers have no trusted proxy in this lane. A private-path success is not public-path evidence.

## Offline validation

These commands render and test only; they neither install nor contact a relay:

```bash
helm template k243 apps/tokenplace-test-lane --namespace tokenplace-k243 \
  --set-string runId=offline-fixture > /tmp/k243-rendered.yaml
SUGARKUBE_SKIP_PREINSTALL_TOOLS=1 pytest -q tests/test_tokenplace_test_lane.py
```

Do not use `offline-fixture` as an operational experiment identifier. Rendering validates isolation,
image/memory/process bounds, rejected overrides, and policy selectors. It cannot prove actual
NetworkPolicy enforcement, scheduling headroom, startup health, or endpoint membership.

The [pinned quota tests](../tests/test_tokenplace_pinned_quota.py) import the application-owned API
middleware from a clean checkout at the exact revision above. In a separate Python 3.12 environment,
prepare that checkout and install its `config/requirements_relay.txt`, `limits==5.8.0` and `pytest`.
Then run (with an absolute checkout path):

```bash
SUGARKUBE_SKIP_PREINSTALL_TOOLS=1 TOKENPLACE_QUOTA_SOURCE=/path/to/pinned/token.place \
  python -m pytest -q tests/test_tokenplace_pinned_quota.py
```

The skip setting disables the repository fixture that otherwise tries to install unrelated CLI
tools. Dependency preparation needs package/source access; the tests themselves use Flask's in-process
client and reject socket connections. They clear inherited environment settings and use temporary
configuration directories. No container, cluster, real relay HTTP request, inference, counter reset,
or privileged counter endpoint is involved. The dedicated
[CI workflow](../.github/workflows/tokenplace-test-lane.yml) runs both suites. Ordinary repository
tests skip the external-source suite when the checkout is absent, and skip render tests without
Helm; neither skip is a pass for that contract.

The tested Flask/Flask-Limiter versions match the pinned source requirements. `limits==5.8.0` fixes
an otherwise transitive dependency for this fixture; it is **not** an assertion about the packages
inside the image. This suite exercises source middleware, actual model-list aliases, and synthetic
error/exempt route handlers; it does not boot the entire relay or qualify E2EE/protocol responses.

| Offline observation | Meaning for later accounting |
| --- | --- |
| Defaults use client identity plus endpoint scope | Do not treat the advertised limit as one global pool |
| `/api/v1/models` and `/v1/models` have separate default buckets | Record the actual endpoint/alias; do not switch aliases to evade a stop |
| Repeated attempts and matched 400/404/500 handlers consume quota | Budget attempted requests, including retries and errors |
| An hourly 429 increments the breached hourly bucket but skips the later daily bucket | Do not infer both counters from total 429s |
| Daily rejection follows the hourly hit in the tested configuration | Rejection accounting depends on the breached window |
| Unmatched 404s bypass default endpoint buckets | A matched handler returning 404 is different |
| Exact public reads, operational paths, relay reads and recognized preflight are exempt | Exemptions depend on path/method; metadata POST is not exempt |
| Fresh independent memory apps have independent counters | This says nothing about shared storage or live headroom |

Separate compute control-plane limits and authenticated exemptions are owned by the pinned
application's `tests/unit/test_rate_limit.py`; this suite does not claim to qualify their complete
identity/credential behavior. Worker polling, retries, progress, results, probes and scrapes must
have their own budget in a later reviewed run.

## K133 handoff and operator gate

Reuse [K133 PR #2907](https://github.com/futuroptimist/sugarkube/pull/2907); do not build a second
workload harness or add a counter endpoint. Its documented offline interface is
`python3 scripts/tokenplace_load_replay.py --plan` and `--scenario healthy`. Its expanded adapter
contract, reviewed here at commit `94a8b19b6f5caeb42f890dc54b33d25a15072292`, documents
`run_protocol_rehearsal(ProtocolAdapter(...))` with explicit crypto, offline transport, virtual
clock, observation callback, prerequisite assertions and expiry. Transport operations are
`open(request, absolute_monotonic_deadline)`, `read(max_bytes)` and `close()`. K133 owns this bounded
protocol adapter, application crypto, deadline enforcement, interruption behavior and offline
transport tests. This lane does not import unpublished implementation symbols or modify that
branch. Merge/review completion of K133 remains a dependency; the snapshot is not a promise that
its API cannot change.

K133's source-binding documentation records serving coordinates; **do not use those coordinates
for a lane experiment or simply substitute a URL**. Its adapter explicitly requires an offline
transport. A separately reviewed network transport, live clock and lane-specific workload/telemetry
evidence providers remain dependencies before any real run. Neither a lane rendering nor a passing
local crypto round trip permits bypassing that offline guard.

The integration contract is the K133 source/image binding and attempt ledger: five public attempts,
five unmatched attempts, and three sequential jobs reserving sixteen attempts each, **58 maximum
test-client attempts**, concurrency one, no automatic retries or redirects. Keep its 64-token job
cap, 150-second client lifecycle, three-second request deadline, acknowledgement/cancellation
accounting, memory/telemetry stop gates and recovery phase. This is not the whole-system traffic
budget, a capacity claim, or a requirement for routine manual inference smoke tests.

Before a separately approved run, the operator must record the exact rendered manifest, unique
run identifier, expiry and owner; verify runtime image/process/backend identity; establish a fresh
process baseline; and review scheduling headroom, independent compute compatibility/allocation,
worker budget, private destination, policy enforcement, telemetry and cleanup ownership. Missing
telemetry or unknown headroom means **zero application traffic**. Existing serving monitoring does
not automatically select this lane; the reviewed adapter needs a lane-specific observation path
with no public discovery or borrowed credentials. The locked chart currently lacks that path and
compute access, intentionally blocking inference until those dependencies are reviewed.

After an approved experiment, the operator owns interruption recovery, verification that compute
has stopped, and removal of only the dedicated lane resources and any separately allocated runner
or compute. Relay cancellation alone does not prove compute termination. Never delete or restart
serving resources as cleanup. Retain only bounded aggregate evidence and provenance; no raw caller
identities, keys, credentials, prompts, ciphertext or response bodies. No deployment, policy apply,
traffic, allocation or removal was performed to produce this chart and its offline results.
