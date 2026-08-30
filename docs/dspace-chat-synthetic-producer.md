# Repository-owned DSPACE chat synthetic producer

This runbook describes construction and review of the staging producer. It does **not** authorize a
host cutover. Live installation, unit mutation, execution, timer activation, cluster access, Helm,
and production mutation require a separate reviewed and explicitly authorized operation.

## Pinned Node runtime

The producer never discovers Node through `PATH`, `/usr/bin/nodejs`, an OS package candidate, a
symlink, or NVM. Configuration selects Node **20.20.2** only at
`/opt/sugarkube/node/v20.20.2-linux-arm64/bin/node`, binding it to the official
`node-v20.20.2-linux-arm64.tar.xz` archive SHA-256, its exact member name, and the member SHA-256.
This provisioning identity remains separate from the DSPACE revision, runner manifest, and retained
producer-asset identities.

Dry-run, status, repair, activation, and rollback validate that same coordinate without executing
it. It must be a non-symlink, singly linked executable regular file with exact digest, `root:root`
ownership and mode `0755`, and an ELF64 little-endian AArch64 header. The real path must equal the
selected path. Thus missing, dangling, aliased, writable, user-home/NVM, 32-bit ARM, wrong-version,
and wrong-digest candidates fail closed before Playwright. Existing systemd protections, including
`ProtectHome=true`, `ProtectSystem=strict`, and `SystemCallArchitectures=native`, are unchanged.

Acquire the named upstream archive separately. These commands first validate it read-only, then
perform the distinct, explicitly authorized provisioning action, and finally inspect the result:

```bash
python3 scripts/install_dspace_chat_synthetic.py provision-node \
  --node-archive /absolute/path/node-v20.20.2-linux-arm64.tar.xz
sudo python3 scripts/install_dspace_chat_synthetic.py provision-node --apply \
  --node-archive /absolute/path/node-v20.20.2-linux-arm64.tar.xz
sudo python3 scripts/install_dspace_chat_synthetic.py status
stat -Lc '%U:%G %a %n' /opt/sugarkube/node/v20.20.2-linux-arm64/bin/node
sha256sum /opt/sugarkube/node/v20.20.2-linux-arm64/bin/node
file /opt/sugarkube/node/v20.20.2-linux-arm64/bin/node
```

Provisioning never contacts a package repository and never invokes Node or systemd. Without
`--apply` it only validates the archive. An alternate `--root` supports host-isolated rehearsal;
reapplication accepts only an already-valid coordinate and is idempotent. Every rollback uses its
retained configuration's exact Node contract. Provisioning does not activate assets or change the
timer, and the alert remains stale until separately authorized installation and a genuinely
successful fresh synthetic result.

## Artifact and trust model

The repository owns the wrapper, runtime, bounded metrics consumer, non-secret coordinates, unit
files, installer, and construction tool. The previous private wrapper SHA
`5a160f1e4c077c09cda5fec062733cd9b31ed8cbfbc5b7f0779403f4a829e70e` is provenance only; it is
not a source input and the new wrapper legitimately differs. The runner’s logical source revision is
the complete DSPACE commit `97ab09f13fb098de928a878bf1fe9b8d13032cb5`; the deployed application identity remains
version `3.1.1`, source `22f506e07e0b5abfd0cf756e9c5827c0458fb4b2`, identity contract
`build-info-v1`, and explicitly selected provider-config contract
`legacy-no-default-provider-v1`.

The logical Git revision is not, by itself, the immutable storage identity. New assets bind the
SHA-256 of the complete generated runner manifest in configuration and store the runner at
`<runnerRevision>-<runnerManifestSha256>`. This permits a reviewed critical-file or manifest-contract
migration at the same Git revision without reusing or overwriting the older revision-only coordinate.
Retained assets created before this migration remain valid and continue to select their legacy
revision-only runner coordinate.

Asset validation likewise separates two manifest contracts. The historical contract is exactly the
bare mapping of every supported asset path to its SHA-256 hash. The current contract is a versioned
object containing that exact mapping and an explicit classification-persistence capability. Unknown,
incomplete, or malformed structures fail closed. Every retained asset must still satisfy its declared
manifest shape and listed hashes, valid configuration, timer persistence, runner identity and
manifest, clean tracked runner content, and browser provenance.

The current capability requires an effective `RuntimeDirectoryPreserve=yes` in the service's
`[Service]` section. It is checked for every current-format retained asset and every render, dry-run,
new installation, and idempotent reapplication. Historical bare-manifest retained assets remain
eligible for inspection and explicit rollback because rewriting immutable assets to impose a later
policy would invalidate their identity. This exception is based only on the supported historical
format, not an asset digest or retention alone: a newly reconstructed versioned asset cannot gain
compatibility from a self-consistent re-hash. Retained assets are never rewritten or upgraded.

That compatibility is limited to revision `97ab09f13fb098de928a878bf1fe9b8d13032cb5`, its exact
revision-only storage name, and the exact seven-file manifest with SHA-256
`36fdab33edc0f1ad518a6d3d247a1bd32d233402387ba57493a9386d78ec9301`. Every declared hash is
validated. The two files absent from that manifest—`frontend/playwright.config.ts` and
`frontend/scripts/utils/ensure-playwright-browsers.js`—must be regular, non-symlinked files whose
bytes equal their tracked blobs at the pinned Git `HEAD`. Unknown digests, arbitrary seven-file
subsets, and missing, untracked, symlinked, or drifted compatibility files fail closed. New
manifest-qualified runners still require the configured digest, exact qualified storage identity,
and all nine critical entries, so the legacy exception does not relax candidate validation.

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
  --pnpm /absolute/toolchain/pnpm --pnpm-version 9.0.0 \
  --browser-source-root /absolute/private/target-root
```

The explicitly selected pnpm executable must report exactly `9.0.0`, matching the pinned DSPACE
commit's `packageManager`. The staging configuration explicitly selects `system-chromium-v1` for
architecture `aarch64`, launcher `/usr/bin/chromium`, and scheduled executable
`/usr/lib/chromium/chromium`. Its committed SHA-256 values are validated along with realpaths,
regular/executable state, `root:root:0755` ownership/mode, and the configured distinct-file
relationship. `--browser-source-root` maps those absolute coordinates into a private root; it must
never point a private rehearsal at the live host by accident. This contract neither accepts
`--browser-bundle` nor installs, downloads, copies, searches for, or modifies a browser.

The alternative explicit `runner-local-playwright-v1` contract preserves the original construction
behavior: supply `--browser-bundle`, copy it into the runner, discover and hash Playwright's exact
runner-local executable, and launch with runner-local `PLAYWRIGHT_BROWSERS_PATH`. No `$HOME` cache
is trusted. Contract selection is mandatory: absence, ambiguity, an unsupported value, or resources
belonging only to the other contract fails closed without fallback. The local pnpm cache must
already contain the exact lockfile's packages. Construction fails for a
missing object, wrong HEAD, dirty tracked/index state, alternates, missing root store, broken
frontend link, unusable Playwright shim/module resolution, or missing critical file. Its manifest
records hashes for the runner, spec, workspace manifests, lockfile, selected browser contract, and
safe browser provenance. At pinned revision `97ab09f13fb098de928a878bf1fe9b8d13032cb5`, the clean
tracked runner configuration already maps `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to Chromium's native
`launchOptions.executablePath`, and its browser-availability helper recognizes an existing override.
Both files are hashed into the immutable manifest and required at runtime. The child also receives
`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`, so neither browser contract can acquire or fall back to a
browser between validation and launch. These facts disprove the earlier executable-mapping
hypothesis. The empty-root private rehearsal passed because it had no revision-only runner coordinate;
the populated live staging-host root rejected the newer valid manifest because that logical revision's
revision-only storage coordinate was already occupied by a different manifest. The logical Git
revision and immutable runner storage identity are therefore distinct coordinates. Runner
validation first derives the exact manifest-qualified storage identity (or the legacy
revision-only identity selected by an older retained asset), verifies the manifest digest, then
separately verifies the manifest’s logical revision and Git HEAD. It rejects
symlinks and paths outside the configured runner root, and then gives every Git inspection
command-scoped trust only for that resolved directory. It ignores persistent and environment-injected
Git configuration and never writes Git configuration. Optional Git locks, including index refreshes,
remain disabled so read-only inspection cannot undo normalized access metadata during a metadata-only
repair. Wildcard or parent-directory trust is never used.

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

For an alternate installation root, both runner and absolute browser coordinates are resolved under
that root; the installer never substitutes the live host's `/usr`. Populate private fixtures before
the command. The preflight first loads the rendered configuration and validates its exact runner
revision against the snapshot basename, manifest hashes, independent Git metadata, dependencies,
and Node/Playwright resolution. It also validates architecture and browser provenance before any
installation mutation. Review all hashes and coordinates. `status` is read-only and, for alternate
roots, reports activation as not queried; only `/` queries unit activation without printing
configuration secrets (the committed configuration contains none). Its
`classificationRuntimeDirectoryPreserve=yes|no` field makes the selected asset's effective service
directive visible; `no` identifies a valid historical-format asset whose service predates
classification-directory persistence rather than suppressing that weaker contract. A failed staging or preflight
leaves installed fixtures unchanged.

## 3. Separately authorized installation and controlled execution

Only after separate approval, invoke apply with the already materialized snapshot:

```bash
sudo python3 scripts/install_dspace_chat_synthetic.py apply \
  --runner-snapshot /absolute/staging/97ab09f13fb098de928a878bf1fe9b8d13032cb5
```

Apply validates the source snapshot before any destination mutation, copies it beneath the configured
runner root, normalizes the copy to `root:<serviceGroup>` with group traversal/read access (and
execute access only where the source executable bit requires it), validates both content and the
configured child's access, and atomically exposes the exact immutable manifest-qualified identity.
Source checkout
ownership and a restrictive source `umask` therefore cannot make the installed runner unusable.
The application-owned ancestors `/var/lib/sugarkube` and the configured runner root are
`root:<serviceGroup>` mode `0710` (group traversal without directory listing); the exact runner
revision and its directories are mode `0750`, executable files are `0750`, and data files are
`0640`. The separate installations and retained-assets subtree remains private. Neither group nor
world receives write access. An
identical pre-existing storage identity is validated and reused; older runner identities and retained
assets are never deleted. Reapplying an already current, fully validated asset is an idempotent
no-op. Only then does apply transactionally replace the validated asset set and switch `current`.
After apply, the operator must run `sudo systemctl daemon-reload` as a separate mandatory
step so the in-memory definitions match disk. The installer never enables, starts, stops, restarts, disables, retries, or executes smoke. A failure during the
installer's transactional asset replacement restores the prior asset set and leaves `current`
unchanged. A failure of the later, separately executed `systemctl daemon-reload` is outside that
transaction and is not automatically rolled back. Stop, classify the reload failure read-only, and
do not execute smoke or activate the timer. Perform an exact rollback only through the separately
authorized rollback procedure before retrying `systemctl daemon-reload`.

The required access model is exact: result root `root:<serviceGroup>` mode `0710`; each invocation
directory `root:<serviceGroup>` mode `0770`; the child-created, same-directory
temporary-and-renamed result `<serviceAccount>:<serviceGroup>` mode `0600`. The current explicit
account and group are both `pi`; the browser runs as that configured account. systemd creates the
volatile result root on each boot. The service
binds the path to systemd's exact 32-hex
`INVOCATION_ID` and UTC epoch start/end window. It cleans only that invocation's path.
Immediately before every child launch the runtime revalidates the selected contract. For the system
contract it passes the already validated exact executable through the pinned runner's supported
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`; it does not hash one binary while launching another. Drift
blocks Playwright before result creation, preserves the previous metric, and therefore retains the
existing stale-signal behavior.

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
When a child returns without a current result, the runtime reads at most 16 KiB of its private
stderr only to select an allowlisted classification: the exact Node executable launch through
`runuser`, browser-executable launch, Playwright configuration, test-before-completion,
completion-publisher, or missing-result after child success or failure. It archives only that
classification, invocation ID, child status, byte count,
truncation and capture-complete flags, and SHA-256 in an atomically replaced, root-only
`latest-classification.json` under
the result root. The systemd runtime directory is preserved across oneshot service exits (but remains
ephemeral across reboot), while invocation-unique result files stay below their own temporary
directories. Only the latest failure is retained: publication atomically replaces the prior record,
failed publication removes its temporary file, and invocation cleanup cannot remove the persistent
record. Raw
output is drained through a pipe, discarded beyond the bounded
in-memory prefix, and never printed or persisted. The drain receives a bounded grace period; when
a descendant retains the pipe, `stderrCaptureComplete` is false and the byte count, truncation
flag, and SHA-256 describe only the immutable bytes captured when that grace period ended. Classify
`preflight`, `overlap`,
`timeout/launch`, `missing`, `provenance`, `malformed`, executed failure, or successful publication
before considering any retry. Do not retry while an invocation
may remain active and never infer success from browser exit alone.

Bind a retained classification to the exact service execution by comparing its `invocation` field
with systemd's invocation ID for that execution; do not infer the binding from timestamps or the
fact that the record is the latest one. The narrowly matched
`node-executable-launch-failure` classification means that `runuser` reported that the fixed
`/usr/bin/node` coordinate could not be executed because it was unavailable to the kernel or
permission was denied. It is selected only for a complete, untruncated diagnostic with that exact
bounded structure and child status 1. It does not prove that the path itself is absent: an
unavailable interpreter or dynamic loader can produce the same operating-system result. The record
intentionally excludes raw stdout, raw stderr, credentials, browser state, and page content. This
classification does not repair the child execution environment. Diagnostics that are incomplete,
truncated, structurally different, or otherwise unknown remain
`current-result-missing-after-child-failure`.

When no valid current bounded result is consumable, the previous metric is preserved byte-for-byte.
It ages into the existing stale alert, making ambiguity fail closed. A valid current failure
publishes success `0`; only a valid current pass publishes `1`, both with that result's current
timestamp. Publication uses same-directory atomic replacement.

Evidence collection is limited to repository revision, installed asset/unit SHA-256 values,
coordinates, ownership/modes, activation state, bounded invocation summary, and metric series/age.
Invocation cleanup is expected lifecycle behavior, not evidence loss.

## 4. Explicit rollback/recovery

### Repair an exact runner's access metadata

The installations and retained-assets store remains intentionally private (`root:root:0700`), so
live `status` and retained-asset validation are root-only operations. Do not weaken that store merely
to let the child inspect it: the child needs only `/var/lib/sugarkube`, the runner root, and the exact
installed runner. Supply the exact retained asset revision reported by the validated private-root
status. For the staging incident, the validated retained asset coordinate is
`9dbccee2be1f57fc7d80a714e3de45a66e860080e07b357c7ddade6e7f343319`, alongside the
approved runner revision and runner manifest SHA-256 shown below. These exact coordinates are
operational authorization and evidence only; retained compatibility is determined by the validated
legacy/current manifest contract, never by an asset-digest allowlist.

First, as root, validate `current`, the exact retained assets, runner Git/content/dependencies,
browser provenance, and the authorized manifest hash without mutation. The report contains only
bounded coordinates and access state:

```bash
sudo python3 scripts/install_dspace_chat_synthetic.py repair-runner-access \
  --revision 97ab09f13fb098de928a878bf1fe9b8d13032cb5 \
  --asset-revision 9dbccee2be1f57fc7d80a714e3de45a66e860080e07b357c7ddade6e7f343319 \
  --runner-manifest-sha256 36fdab33edc0f1ad518a6d3d247a1bd32d233402387ba57493a9386d78ec9301
```

After separate authorization for this metadata-only repair, repeat with `--apply`. This operation
inspects every entry in the complete runner access plan with `lstat()`, then writes only mismatched
ownership or modes on the application-owned runner parents and exact runner. Already-correct
entries are not passed to `chown` or `chmod`, so metadata writes for a large immutable runner are
bounded by the number of mismatches, even though inspection still covers the complete plan. It does
not replace assets, switch `current`, publish metrics, touch the browser, call systemd, execute
smoke, retry, or roll back:

```bash
sudo python3 scripts/install_dspace_chat_synthetic.py repair-runner-access --apply \
  --revision 97ab09f13fb098de928a878bf1fe9b8d13032cb5 \
  --asset-revision 9dbccee2be1f57fc7d80a714e3de45a66e860080e07b357c7ddade6e7f343319 \
  --runner-manifest-sha256 36fdab33edc0f1ad518a6d3d247a1bd32d233402387ba57493a9386d78ec9301
sudo python3 scripts/install_dspace_chat_synthetic.py status
```

Stop if any exact coordinate, content, dependency, Git, browser, retained asset, or child-access
validation fails. Do not reapply the installation or alter the timer. Only after child access is
revalidated may an operator seek separate authorization for `systemctl daemon-reload`, then one
controlled execution, and then bounded scheduled-health observation. Each is a distinct decision;
there is no automatic retry or rollback.

### Roll back retained repository assets

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

The command loads the retained asset’s own configuration, validates its exact legacy or
manifest-qualified runner identity and browser contract, and only then switches assets. Thus rollback
selects the original runner as well as the exact asset. Rollback remains explicit and may
intentionally restore a historical service contract without classification runtime-directory
persistence; every newly rendered candidate must still satisfy the current persistence requirement.
`status` reports `runnerRevision`,
`runnerStorageIdentity`, and `runnerManifestSha256`; operators must verify all three without renaming
runners, weakening manifest checks, or adding persistent Git safe-directory configuration. The command
rejects an absent, incomplete, or hash-mismatched retained revision and does not change
timer/service activation. Observe the same status and metric-age evidence afterward. Any live
cutover or recovery after merge remains a separate reviewed and explicitly authorized operation.
