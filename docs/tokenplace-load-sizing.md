# Bounded token.place memory sizing replay

K133 retains the relay memory request and limit at **256Mi**. This toolkit prepares a small
controlled workload; it does not measure maximum capacity or attempt quota exhaustion.
The historical sampled working-set maximum of 69.66Mi over one day is not load-capacity proof.
Quota headroom and client isolation remain separate prerequisites, tracked by K243.

## Offline commands

From the repository root, with Python 3.10 or newer:

```bash
python3 scripts/tokenplace_load_replay.py --plan
python3 scripts/tokenplace_load_replay.py --scenario healthy
python3 scripts/tokenplace_load_replay.py --scenario pending
pytest -q tests/test_tokenplace_load_replay.py
```

The last replay intentionally stops and exits with status 1. Other built-in failure fixtures are
`quota`, `memory`, `missing_telemetry`, and `ack_failure`. The healthy fixture takes 39 minutes of
virtual time, with no wall-clock waiting. It uses all twelve retrieval slots per job and makes
55 simulated attempts. Three additional cancellation attempts are reserved in the 58-attempt
ceiling; a real failure stops the sequence instead of continuing to spend that reservation.

**There is no live execution, network, cluster, or cryptographic adapter in this command.**
It accepts no hostname, credentials, evidence file, execution flag, or external fixture file.
Synthetic keys, ciphertext and decryption assertions exercise the protocol state machine only.
Every result states that live execution, encryption verification, capacity/headroom proof, and
worker-traffic qualification are false. Passing a replay is never an execution authorization.

The stock application chat client cannot simply be run under this budget: it polls approximately
every two seconds, lacks this attempt ceiling, and does not implement the full acknowledgement
flow required here. A future independently reviewed adapter must reuse application-owned
encryption and verify actual decryption. This replay deliberately does not copy encryption code,
import an arbitrary checkout, or pretend that fixture ciphertext provides E2EE.

## Source and workload binding

The plan is bound to the image reviewed by the K241 inventory, whose matching declared and runtime
image identifier was observed on October 7, 2026. That observation is not continuing health evidence.

```text
image: ghcr.io/futuroptimist/tokenplace-relay@sha256:5d761cefc0495926b63da1e0a4119155a005e165e469da90e7f19be0f7fdff8e
source: 5e190f5c6ff66e9c05934a0e2ce2c1a440b9ea49
namespace/deployment: tokenplace/tokenplace
container: relay
replicas: 1
memory request/limit: 256Mi/256Mi
```

The protocol contract comes from the deployed revision's
[relay routes](https://github.com/futuroptimist/token.place/blob/5e190f5c6ff66e9c05934a0e2ce2c1a440b9ea49/relay.py),
[reservation store](https://github.com/futuroptimist/token.place/blob/5e190f5c6ff66e9c05934a0e2ce2c1a440b9ea49/relay_state_store.py),
[compute client](https://github.com/futuroptimist/token.place/blob/5e190f5c6ff66e9c05934a0e2ce2c1a440b9ea49/utils/networking/relay_client.py),
and [chat client](https://github.com/futuroptimist/token.place/blob/5e190f5c6ff66e9c05934a0e2ce2c1a440b9ea49/client.py).
Current application source may have different storage semantics; never substitute it for the
deployed revision. Rebinding this plan requires source/protocol review, not just replacing a digest.

## Fixed workload and accounting

| Phase | Duration | Test-client workload |
| --- | --- | --- |
| Baseline | 5 minutes | No requests |
| Public | 5 minutes | One GET per minute: `/`, `/api/v1/meta`, `/api/v1/version`, `/healthz`, `/livez` |
| Unmatched | 5 minutes | One GET per minute to `/__k133_unmatched_probe__`; no random suffix or query |
| E2EE | 9 minutes | At most three sequential jobs, starting at phase seconds 0, 180, and 360 |
| Recovery | 15 minutes | No requests |

Public responses must be 200; the deliberately unmatched response must be 404. Each E2EE job uses
model `qwen3-8b-instruct`, tier `8k-fast`, a fresh synthetic identity, no prior conversation, and
one encrypted application request containing the message `Reply with OK.` and options
`max_tokens=64`, `temperature=0`, `stream=false`. Model/tier substitution and fallback are rejected.
Availability and token-cap enforcement on a real compute node remain unproven.

Per job, reserve exactly these maxima:

| Operation | Method and route | Attempts |
| --- | --- | --- |
| Select and reserve | GET `/api/v1/relay/servers/next` | 1 |
| Submit ciphertext | POST `/api/v1/relay/requests` | 1 |
| Retrieve | POST `/api/v1/relay/responses/retrieve` | 12 |
| Acknowledge | POST `/api/v1/relay/responses/retrieve` | 1 |
| Cancel if required | POST `/api/v1/relay/requests/cancel` | 1 |

Total reservation: `5 + 5 + 3 * 16 = 58` test-client attempts. Existing probes, scrapes, worker
polling, and induced worker progress/results are **not included** and need separate reviewed
accounting. This number is not a whole-system traffic ceiling.

The client lifecycle is at most 150 seconds per job, with concurrency one, no retries or redirects,
and an absolute three-second deadline per request including response-body reading. Retrieval slots
start at 10-second intervals after admission, from 10 through 120 seconds. A pending 202 is allowed;
success stops polling immediately. Missed slots cannot be compressed or retried. A future live
adapter must enforce actual deadlines and streaming byte limits; fixture response sizes and delays
only test the decision contract.

The application request is at most 1KiB; the complete plaintext protocol envelope before encryption
is at most 4KiB. Every HTTP request and response body is at most 16KiB. Decrypted assistant content
is at most 4KiB. Serialization and UTF-8 bytes count toward limits. Do not increase a ceiling to
make an incompatible response pass.

## Reservation, acknowledgement, and cleanup

Selection creates a reservation even though it uses GET. Cleanup coordinates are retained before
selection so an uncertain response cannot cause an automatic retry. Submission preserves the
returned reservation token and exact server deadline: the store rejects rewritten deadlines.
The 150-second client budget is therefore **not** a promise of a 150-second server lifetime.
Submission returns a retrieval credential and remaining-time fields, not a new absolute deadline.

Retrieval uses that credential and checks outer protocol/version/client/request binding. The
decrypted fixture checks protocol/version/request binding and a nonempty assistant message without
an error. The deployed inner response does not contain a client public key. Success requires one
acknowledgement with the returned acknowledgement token, followed by the recovery phase.

Any failure stops further jobs. At most one cancellation attempt uses the original identity and
cancellation proof, within the attempt, client-time, identity, and expiry boundaries. Uncertain
admission is not retried. Expiry or identity drift can prevent cleanup; that remains explicitly
unconfirmed. A relay cancellation response does not prove that compute stopped. No process restart,
counter reset, replacement job, or unbounded cleanup loop is allowed. A future adapter needs a
reviewed process-interruption and outstanding-work recovery procedure before live execution.
If completion already won, cancellation returns the existing `completed` outcome, not `cancelled`.
In particular, a failed or lost acknowledgement leaves cleanup unconfirmed in this replay.

## Observation gates and remaining authorization

Use existing telemetry with cadence at most 30 seconds. Stop when a sample is two cadences old,
or sooner if any sample reaches 192Mi working set (75% of 256Mi). Baseline and recovery require
working set strictly below 70%. Stop on any new restart/OOM, readiness/scrape failure, coordinate
drift, unexpected status, malformed response, timeout, missing telemetry, or budget exhaustion.
RSS and working-set samples are observations, not a true unsampled peak or capacity proof.

The replay's prerequisite booleans are synthetic assertions only. A live adapter requires separate,
freshly reviewed evidence for authorization, applicable per-client quota headroom, isolated client
identity, edge/origin behavior, compute compatibility, and worker-traffic budgets. It also requires
authoritative workload/telemetry checks, actual application crypto, private lifecycle ownership,
and a reviewed per-run expiry that covers all phases and cleanup. No campaign date is a permanent
default. Unknown headroom or isolation means zero application traffic. A lower available budget
requires a separately reviewed smaller plan, not an implicit skip or a manufactured success.

Preserve memory, images, probes, metrics discovery, compute configuration, and quotas. Keep live
quota qualification separate from memory sizing. Retain only finite operation/status counts,
timing, sampled memory summaries, and finite outcome/cleanup classes. Do not retain raw observed
paths or queries, caller identities, request identifiers, keys, credentials, payloads, or responses.
The replay's in-memory transport transcript contains synthetic fixtures only and is never printed.

The next executable step is an independently reviewed live adapter with those prerequisites;
this repository-only replay does not authorize or implement that step.
