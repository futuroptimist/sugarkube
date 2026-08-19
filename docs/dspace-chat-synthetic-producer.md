# Repository-owned DSPACE chat synthetic producer

This package replaces behavioral provenance from the former private/manual staging recovery with
reviewable source. The old wrapper hash
`5a160f1e4c077c09cda5fec062733cd9b31ed8cbfbc5b7f0779403f4a829e70e` is recorded only as a
baseline: it is not a source input, and the repository wrapper legitimately has another hash. Live
cutover is **not** part of repository construction or installation and requires a separate reviewed,
explicitly authorized operation.

## Trust and filesystem model

The checked-in JSON explicitly selects the release, source and runner commits, `build-info-v1`, and
`legacy-no-default-provider-v1`; absence never selects a contract. The legacy provider contract is
accepted only for DSPACE 3.1.1 at source `22f506e07e0b5abfd0cf756e9c5827c0458fb4b2`.
The runner is a complete detached Git checkout, including its object database, exact lockfile and
root `node_modules/.pnpm` store. Complete Git metadata proves the commit and cleanliness without the
source checkout; the root store is required because pnpm workspace links resolve through it.

The result root is `root:pi` mode `0710`; each invocation directory is `root:pi` mode `0770`; and
the unprivileged `pi` child atomically renames its same-directory temporary result to a `pi:pi`, mode
`0600` final file. The wrapper accepts only its exact `INVOCATION_ID`, time window, owner, mode,
schema and coordinates, then removes only that invocation directory. Normal cleanup is not evidence
loss. Invalid, missing, late, or timed-out results leave the prior metric byte-for-byte unchanged.
A passing Playwright summary does not prove that the bounded result was published.

## 1. Construct and validate a runner

From an explicitly identified local, clean DSPACE checkout at the exact commit (never from a live
host), run:

```bash
python3 scripts/materialize_dspace_chat_runner.py \
  --source /absolute/path/to/local/dspace \
  --repository https://github.com/democratizedspace/dspace.git \
  --revision 97ab09f13fb098de928a878bf1fe9b8d13032cb5 \
  --output /safe/staging/97ab09f13fb098de928a878bf1fe9b8d13032cb5
```

Construction uses frozen lockfile resolution, validates Playwright and module resolution, rejects
alternates and broken frontend links, and writes hashes to `sugarkube-runner-manifest.json`.

## 2. Render and inspect without mutation

```bash
python3 scripts/install_dspace_chat_synthetic.py dry-run
python3 scripts/install_dspace_chat_synthetic.py status --root /temporary/root
```

Dry-run is the default. Tests should always use `--root` with a temporary directory. Review rendered
hashes, coordinates, unit provenance and the persistent timer before authorizing any later operation.

## 3. Install, execute, and activate separately

Only after separate host authorization, `apply` stages and validates all assets before atomic
replacement. It does not call systemctl. A controlled execution and timer activation are distinct
operator decisions: first use `systemctl start dspace-chat-synthetic.service`, inspect its bounded
summary and metric freshness, then separately use `systemctl enable --now
dspace-chat-synthetic.timer`. The timer has `Persistent=true`; installation never enables, starts,
stops, restarts, or disables it.

## 4. Read-only failure classification

Before considering a retry, use `status`, `systemctl show` for activation state and unit hashes, and
read only metric metadata and bounded wrapper summaries. Classify preflight, overlap, launch,
timeout, absent result, result validation, or metric publication failure. Do not print raw results,
journals, credentials, Secret values, browser output, or private artifacts. Do not retry until a new
reviewed operator decision; the producer never retries, restarts, rolls back, or invokes a second run.

## 5. Explicit recovery and evidence

An applied update retains the preceding validated asset set. Recovery requires its exact revision:

```bash
python3 scripts/install_dspace_chat_synthetic.py rollback --revision EXACT_RETAINED_REVISION
```

Rollback validates every retained hash and does not manipulate systemd. Collect only configuration,
runner-manifest and unit hashes, coordinates, activation states, invocation-bound summaries, and
metric timestamp/value. Never collect payloads or sensitive artifacts. After merge, the remaining
work is a separately reviewed host cutover: materialize/copy the runner, prepare exact ownership and
modes, apply assets, perform one controlled run, and explicitly activate and observe the schedule.
