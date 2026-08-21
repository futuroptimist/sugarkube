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

Browser selection is also an explicit, fail-closed contract. The staging configuration selects
`system-chromium-v1` for `aarch64` and pins the regular `root:root` mode `0755` launcher
`/usr/bin/chromium` and scheduled executable `/usr/lib/chromium/chromium` by their separate SHA-256
values and real paths. The launcher is provenance evidence; the executable is passed to the pinned
DSPACE Playwright configuration as `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`, so the verified file is
the file Playwright launches. The runtime does not search `$PATH`, infer a browser from files on the
host, or fall back to a runner-local bundle. It repeats this validation before every invocation.

## 1. Construct an independent runner

Use only an explicitly identified, clean local DSPACE checkout. Construction uses the exact
lockfile, frozen and offline; it never contacts GitHub or resolves new package versions.

```bash
python3 scripts/install_dspace_chat_synthetic.py materialize \
  --source /absolute/path/to/local/dspace \
  --revision 97ab09f13fb098de928a878bf1fe9b8d13032cb5 \
  --repository-identity https://github.com/democratizedspace/dspace.git \
  --output /absolute/staging/97ab09f13fb098de928a878bf1fe9b8d13032cb5 \
  --pnpm /absolute/toolchain/pnpm --pnpm-version 9.0.0
```

The explicitly selected pnpm executable must report exactly `9.0.0`, matching the pinned DSPACE
commit's `packageManager`. Under the selected system contract no browser is downloaded, copied, or
installed and `--browser-bundle` is rejected. The local pnpm cache must already contain the exact lockfile's packages. Construction fails for a
missing object, wrong HEAD, dirty tracked/index state, alternates, missing root store, broken
frontend link, unusable Playwright shim/module resolution, or missing critical file. Its manifest
records hashes for the runner, spec, workspace manifests, and lockfile as well as the selected safe
browser provenance. If a future repository configuration explicitly selects
`runner-local-playwright-v1`, materialization instead requires `--browser-bundle`, copies and hashes
the Playwright-selected executable below `playwright-browser`, and runtime sets only the
runner-local `PLAYWRIGHT_BROWSERS_PATH`. Neither contract can fall back to the other.

## 2. Validate and dry-run installation

Complete installer validation requires the exact materialized snapshot and supports an alternate
root for a non-mutating rehearsal:

```bash
python3 scripts/install_dspace_chat_synthetic.py dry-run \
  --runner-snapshot /absolute/staging/97ab09f13fb098de928a878bf1fe9b8d13032cb5
python3 scripts/install_dspace_chat_synthetic.py dry-run --root /tmp/rehearsal-root \
  --runner-snapshot /absolute/staging/97ab09f13fb098de928a878bf1fe9b8d13032cb5
python3 scripts/install_dspace_chat_synthetic.py status --root /tmp/rehearsal-root
```

`--root` is both the installation target root and the source root for absolute system-browser
coordinates: `/usr/bin/chromium` is therefore validated as
`/tmp/rehearsal-root/usr/bin/chromium` in that example, never against the live host's `/usr`.
Alternate-root status and dry-run remain non-mutating and never query live systemd. The configured
architecture must match the platform being validated; private rehearsal roots should be validated
on their target architecture. Do not populate a private root by copying from or changing the live
host through this installer.

The preflight first loads the rendered configuration and validates the complete browser contract,
including architecture, paths, real paths, hashes, regular/executable state, owner, group, mode, and
declared launcher/executable provenance relationship, before any installation mutation. It also
validates its exact runner revision against
the snapshot basename, manifest hashes, independent Git metadata, dependencies, and Node/Playwright
resolution. Review all hashes and coordinates. `status` is read-only and, for alternate roots, reports activation as not queried; only `/` queries unit activation without
printing configuration secrets (the committed configuration contains none). A failed staging or
preflight leaves installed fixtures unchanged.

## 3. Separately authorized installation and controlled execution

Only after separate approval, invoke apply with the already materialized snapshot:

```bash
sudo python3 scripts/install_dspace_chat_synthetic.py apply \
  --runner-snapshot /absolute/staging/97ab09f13fb098de928a878bf1fe9b8d13032cb5
```

Apply validates the source snapshot before any destination mutation, copies it beneath the configured
runner root, validates the copy again, and atomically exposes the exact immutable revision. An
identical pre-existing revision is validated and reused; older runner revisions are retained. Only
then does apply transactionally replace the validated asset set and switch `current`.
After apply, the operator must run `sudo systemctl daemon-reload` as a separate mandatory
step so the in-memory definitions match disk. The installer never enables, starts, stops, restarts, disables, retries, or executes smoke. A failure during the
installer's transactional asset replacement restores the prior asset set and leaves `current`
unchanged. A failure of the later, separately executed `systemctl daemon-reload` is outside that
transaction and is not automatically rolled back. Stop, classify the reload failure read-only, and
do not execute smoke or activate the timer. Perform an exact rollback only through the separately
authorized rollback procedure before retrying `systemctl daemon-reload`.

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
