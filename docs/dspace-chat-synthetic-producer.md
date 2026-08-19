# DSPACE chat synthetic producer

This runbook describes repository-owned source and reviewed coordinates for the
staging DSPACE `/chat` producer. It is **not** authorization to change a host.
Live cutover remains a separate, reviewed, explicitly authorized operation.
The private recovery wrapper and incident evidence are behavioral provenance,
not build inputs. Consequently, the repository wrapper is expected to differ
from the previously observed private-wrapper SHA-256
`5a160f1e4c077c09cda5fec062733cd9b31ed8cbfbc5b7f0779403f4a829e70e`.

## Trust and filesystem contract

[`staging.json`](../config/dspace-chat-synthetic/staging.json) explicitly binds
runner `97ab09f13fb098de928a878bf1fe9b8d13032cb5`, DSPACE `3.1.1` source
`22f506e07e0b5abfd0cf756e9c5827c0458fb4b2`, `build-info-v1`, and
`legacy-no-default-provider-v1`. The legacy provider contract is allowed only
for that exact tuple; absence of a provider field never selects a contract.
The record also binds the non-secret token.place provider origin/model, timeout,
runner, result, lock, and node-exporter metric paths.

The runner is a full, independent Git checkout. Complete Git metadata is needed
to prove the commit and object closure later; a worktree export cannot do that.
The root `node_modules/.pnpm` store and frontend links are needed because pnpm's
workspace layout resolves packages through both, rather than through an
untracked global mutable store. Critical inputs are recorded in the runner
manifest. Construction rejects dirty state and alternates.

On a future authorized host, the result root must be `root:pi` mode `0710`, each
invocation directory `root:pi` mode `0770`, and the child-published result
`pi:pi` mode `0600`. The browser publishes atomically by writing a temporary
file in its invocation directory, setting mode `0600`, and renaming it to
`result.json`. The wrapper removes only that invocation-owned directory.

## 1. Construct and validate the runner

Use an already present, trusted local DSPACE checkout; construction is offline
and never changes that repository:

```bash
python scripts/materialize_dspace_chat_runner.py \
  --source /absolute/path/to/local/dspace \
  --revision 97ab09f13fb098de928a878bf1fe9b8d13032cb5 \
  --destination /absolute/staging/97ab09f13fb098de928a878bf1fe9b8d13032cb5
```

The command uses the exact lockfile with `pnpm install --frozen-lockfile
--offline`, then validates Git object closure, the root pnpm store, frontend
links, the Playwright shim, Node resolution, and file hashes. Missing cached
packages fail rather than contacting a registry.

## 2. Validate and dry-run installation

These default operations are read-only and can target a temporary filesystem:

```bash
python scripts/install_dspace_chat_synthetic.py validate --runner /absolute/staging/97ab09f13fb098de928a878bf1fe9b8d13032cb5
python scripts/install_dspace_chat_synthetic.py status --root /temporary/root
python scripts/install_dspace_chat_synthetic.py install --root /temporary/root --runner /absolute/staging/97ab09f13fb098de928a878bf1fe9b8d13032cb5
```

Only a separately reviewed command with `install --apply` replaces files. It
stages and validates the complete revision first, uses atomic per-file replaces,
retains prior files, and does not call `systemctl`. Review hashes reported by
`status` and unit provenance before proceeding.

## 3. Controlled execution and timer activation

After separately authorized installation, an operator may invoke exactly one
controlled service execution. Do not infer success from a passing Playwright
summary: result publication, ownership, mode, schema, invocation ID, and time
window validation can still fail. Review only bounded wrapper status and metric
metadata; never copy raw browser output, results, credentials, Secrets, or raw
journals into evidence.

Timer activation is another explicit operator decision. The installed timer has
`Persistent=true`, but neither installer nor wrapper enables or starts it. A
future cutover authorization must specify the exact `systemctl enable` and
`systemctl start` actions. Observe at least two scheduled intervals and verify
the unit invocation IDs, timestamps, metric age, and alert state.

## Failure classification and evidence

Before any retry, use read-only `status`, `systemctl show` properties, file
metadata, and SHA-256 values to classify: preflight/coordinate rejection,
overlap, launch/timeout, absent publication, ownership/mode, malformed or stale
result, or metric publication. Do not print raw results or journals. Record the
repository commit, config and unit hashes, runner-manifest hash, exact
`INVOCATION_ID`, UTC start/end summary, exit state, and prior/current metric
hash. A missing, late, malformed, or otherwise invalid current bounded result
preserves the prior metric byte-for-byte. There is no automatic retry, second
invocation, restart, restore, or rollback.

## Explicit rollback

Rollback is never automatic. Select the exact 40-character revision retained by
a previous validated install, first dry-run it, and only then use `--apply` under
separate authorization:

```bash
python scripts/install_dspace_chat_synthetic.py rollback --revision <exact-sha>
python scripts/install_dspace_chat_synthetic.py rollback --revision <exact-sha> --apply
```

Rollback changes files only. Service execution and timer activation remain
separate operator actions. After merge, the remaining work is still the live
host cutover: transfer the independently built runner, validate host ownership
and paths, install, execute once, explicitly activate the timer, and observe it.
