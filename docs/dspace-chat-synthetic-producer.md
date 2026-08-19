# Repository-owned DSPACE chat synthetic producer

This runbook describes construction and review of the staging producer. It does **not** authorize a
host cutover. Live installation, unit mutation, execution, timer activation, cluster access, Helm,
and production mutation require a separate reviewed and explicitly authorized operation.

## Artifact and trust model

The repository owns the wrapper, runtime, bounded metrics consumer, non-secret coordinates, unit
files, installer, and construction tool. The previous private wrapper SHA
`5a160f1e4c077c09cda5fec062733cd9b31ed8cbfbc5b7f0779403f4a829e70e` is provenance only; it is
not a source input and the new wrapper legitimately differs. The approved runner is the complete
DSPACE commit `97ab09f13fb098de928a878bf1fe9b8d13032cb5`; the deployed application identity remains
version `3.1.1`, source `22f506e07e0b5abfd0cf756e9c5827c0458fb4b2`, identity contract
`build-info-v1`, and explicitly selected provider-config contract
`legacy-no-default-provider-v1`.

Complete Git metadata is retained so the snapshot can prove its exact HEAD and object integrity
without the source checkout, alternates, hard-linked objects, or a shared object store. The root
`node_modules/.pnpm` store and frontend dependency links are retained because pnpm workspace links
alone are not dependencies: their package targets live in that root content-addressed layout.

## 1. Construct an independent runner

Use only an explicitly identified, clean local DSPACE checkout. Construction uses the exact
lockfile, frozen and offline; it never contacts GitHub or resolves new package versions.

```bash
python3 scripts/install_dspace_chat_synthetic.py materialize \
  --source /absolute/path/to/local/dspace \
  --revision 97ab09f13fb098de928a878bf1fe9b8d13032cb5 \
  --repository-identity https://github.com/democratizedspace/dspace.git \
  --output /absolute/staging/97ab09f13fb098de928a878bf1fe9b8d13032cb5 \
  --pnpm /absolute/toolchain/pnpm --pnpm-version <exact-version> \
  --browser-bundle /absolute/path/to/browser-bundle
```

The explicitly selected pnpm executable must report the requested version. The supplied local browser bundle is copied into the runner and used through a runner-local `PLAYWRIGHT_BROWSERS_PATH`; no `$HOME` cache is trusted. The local pnpm cache must already contain the exact lockfile's packages. Construction fails for a
missing object, wrong HEAD, dirty tracked/index state, alternates, missing root store, broken
frontend link, unusable Playwright shim/module resolution, or missing critical file. Its manifest
records hashes for the runner, spec, workspace manifests, and lockfile.

## 2. Validate and dry-run installation

The installer defaults to non-mutating validation and supports an alternate root for rehearsal:

```bash
python3 scripts/install_dspace_chat_synthetic.py
python3 scripts/install_dspace_chat_synthetic.py dry-run --root /tmp/rehearsal-root
python3 scripts/install_dspace_chat_synthetic.py status --root /tmp/rehearsal-root
```

Review all hashes and coordinates. `status` is read-only and, for alternate roots, reports activation as not queried; only `/` queries unit activation without
printing configuration secrets (the committed configuration contains none). A failed staging or
preflight leaves installed fixtures unchanged.

## 3. Separately authorized installation and controlled execution

Only after separate approval, an operator may stage the runner at
`/var/lib/sugarkube/dspace-chat-runners/<exact-revision>`, then invoke `apply`. Apply atomically
replaces files only after validating the whole staged set and retains the prior validated revision.
After apply, the operator must run `sudo systemctl daemon-reload` as a separate mandatory
step so the in-memory definitions match disk. The installer never enables, starts, stops, restarts, disables, retries, or executes smoke. If replacement or
reload fails, it restores the prior asset set and leaves the `current` revision pointer unchanged.

The required access model is exact: result root `root:pi` mode `0710`; each invocation directory
`root:pi` mode `0770`; the child-created, same-directory temporary-and-renamed result `pi:pi` mode
`0600`. The browser runs as `pi`. systemd creates the volatile result root on each boot. The service
binds the path to systemd's exact 32-hex
`INVOCATION_ID` and UTC epoch start/end window. It cleans only that invocation's path.

After inspecting status, a controlled one-shot and timer activation are distinct, explicit operator
actions; neither is performed by installation:

```bash
sudo systemctl start dspace-chat-synthetic.service
# Observe and classify before the separately approved scheduling action:
sudo systemctl enable --now dspace-chat-synthetic.timer
```

The timer retains `Persistent=true`. A successful Playwright summary does **not** prove bounded
result publication: only a current, correctly owned/mode, in-window result followed by atomic metric
replacement proves publication.

## Failure classification and observation

Read status, hashes, metric timestamps, unit exit status, and bounded `outcome=` summaries first.
Do not print credentials, Secret values, raw results, browser output, or unrestricted journals.
Classify `preflight`, `overlap`, `timeout/launch`, `missing`, `provenance`, `malformed`, executed
failure, or successful publication before considering any retry. Do not retry while an invocation
may remain active and never infer success from browser exit alone.

When no valid current bounded result is consumable, the previous metric is preserved byte-for-byte.
It ages into the existing stale alert, making ambiguity fail closed. A valid current failure
publishes success `0`; only a valid current pass publishes `1`, both with that result's current
timestamp. Publication uses same-directory atomic replacement.

Evidence collection is limited to repository revision, installed asset/unit SHA-256 values,
coordinates, ownership/modes, activation state, bounded invocation summary, and metric series/age.
Invocation cleanup is expected lifecycle behavior, not evidence loss.

## 4. Explicit rollback/recovery

Rollback is never automatic. After read-only classification and separate authorization, select an
exact retained validated revision:

```bash
python3 scripts/install_dspace_chat_synthetic.py rollback \
  --revision <exact-retained-asset-revision>
# After separate authorization:
python3 scripts/install_dspace_chat_synthetic.py rollback --apply \
  --revision <exact-retained-asset-revision>
sudo systemctl daemon-reload
```

The command rejects an absent, incomplete, or hash-mismatched retained revision and does not change
timer/service activation. Observe the same status and metric-age evidence afterward. Any live
cutover or recovery after merge remains a separate reviewed and explicitly authorized operation.
