# DSPACE chat synthetic producer

This repository owns the wrapper, non-secret coordinates, construction tool, units, and validation
logic for the staging chat synthetic. The earlier private wrapper SHA
`5a160f1e4c077c09cda5fec062733cd9b31ed8cbfbc5b7f0779403f4a829e70e` is provenance only: it is
not a source input and the repository wrapper legitimately has a different hash. **Nothing in this
runbook authorizes a live cutover.** Host installation and activation require a separate reviewed,
explicitly authorized operation.

## Trust and filesystem model

[`config/dspace-chat-synthetic.json`](../config/dspace-chat-synthetic.json) explicitly binds the
immutable runner and deployed source revisions, DSPACE 3.1.1, `build-info-v1`, the narrowly approved
`legacy-no-default-provider-v1` contract, provider, origin, model, timeout, and paths. Contract choice
is never inferred from an absent field. Complete Git metadata is retained so HEAD, object
availability, repository identity, cleanliness, and independence from alternates remain auditable.
The root `node_modules/.pnpm` store and frontend links are retained because pnpm workspace links are
not a self-contained frontend install.

The result root is `root:pi` mode `0710`; each invocation directory is `root:pi` mode `0770`; and the
unprivileged `pi` child atomically renames its same-directory temporary result to a `pi:pi` mode
`0600` final file. The wrapper accepts only the current `INVOCATION_ID` and bounded UTC epoch window,
then removes only that invocation directory. Cleanup is normal lifecycle behavior, not evidence
loss. Missing, stale, malformed, pre-existing, shared, wrongly owned, wrongly permissioned, timed
out, or launch-failed results leave the prior metric byte-for-byte unchanged. A valid failure emits
success `0`; only a valid pass emits `1`. A passing Playwright summary alone does **not** prove that
result publication succeeded.

## Separate operator steps

All examples below are review examples. Use temporary targets until a live operation is separately
authorized. They never contact a cluster or invoke Helm.

1. **Construct.** From an explicitly identified clean local DSPACE checkout at the exact runner
   commit, run `python3 scripts/dspace_chat_synthetic.py materialize --config
   config/dspace-chat-synthetic.json --source /absolute/local/dspace --revision
   97ab09f13fb098de928a878bf1fe9b8d13032cb5 --destination /absolute/staging/runner`. The offline,
   frozen-lockfile install must already have all pnpm packages available; no mutable global store is
   used as an installed dependency.
2. **Validate/dry run.** Run the `validate` subcommand, then `install` with explicit wrapper, service,
   timer, runner, and temporary `--prefix` arguments. Without `--apply`, installation is
   non-mutating. Review hashes with `status`; it prints coordinates and provenance, not secrets.
3. **Install.** Only after separate authorization, repeat with `--apply`. Staging is validated first,
   replacement is atomic per file, retained revision directories are not deleted, and no unit is
   enabled, started, stopped, restarted, or disabled.
4. **Controlled execution.** Review `systemctl cat` and unit hashes, create the exact ownership model,
   and invoke the oneshot once. Do not retry automatically. Record only bounded status, timestamps,
   hashes, `systemctl show` activation properties, and metric metadata—not raw journals, results,
   browser output, credentials, Secrets, or wrapper contents.
5. **Timer activation.** This is a distinct authorized action. Confirm `Persistent=true`, then enable
   the timer explicitly. Observe at least two scheduled windows and metric freshness; installation
   never activates it.
6. **Classify before retry.** Read only service exit status, `InvocationID`, start/end properties,
   file owner/mode, configured hashes, timer state, and metric timestamp. Classify preflight,
   overlap, launch, timeout, publication, schema/window, or valid journey failure. Do not expose raw
   payloads and do not retry until a reviewer explicitly authorizes it.
7. **Rollback.** Select an exact retained commit with `rollback --prefix / --revision <40-hex>`.
   Validation precedes the atomic pointer change. Rollback never restarts a service; controlled
   execution and timer decisions remain separate. An invalid or absent retained revision fails
   closed without changing the pointer.

Residual operational risk includes browser/runtime compatibility, availability of the offline pnpm
package set during construction, host account/permission drift, and staging network behavior. These
can only be resolved during the separately reviewed host cutover and observation; merge alone makes
no host change.
