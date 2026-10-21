# Resolver lifecycle qualification proposal

Status: prepared for review, **not executed or approved for VM execution**.
The earlier synthetic proof and repository unit tests do not qualify this harness,
real systemd lifecycle integration, or K3s recovery.

## Proposed execution envelope

Use a new disposable VM named `sugarkube-lifecycle-proof-v1`: one CPU, 1 GiB RAM,
10 GiB virtual disk, no NIC, shared folders, login access or cluster credentials.
Use the lab owner's pristine Ubuntu image with Python 3.12, systemd 255.4,
kernel 6.8.0-142 and real util-linux tools. No packages are fetched in the guest.
Budget at most 12 GiB additional disk under the 140 GiB total cap. Check capacity
before creating it; do not delete retained evidence to make room.

The 30-minute window allocates five minutes to boot, fifteen to tests and ten to
cleanup and graceful shutdown. The reviewed `resolver_oneshot.py` boot wrapper records
progress and preserves failure evidence. No reboot, hard power-off, credential
setup, security-policy change or privileged-executor fallback is authorized.
A timeout or uncertain cleanup is incomplete qualification: report and stop,
preserving the VM for owner inspection. Existing VMs, q3 divergence, timers,
network, switch, staging and production remain untouched.

Before approval, the lab owner must supply the exact pristine-image SHA256,
full Python/systemd/util-linux/iproute2 package versions and kernel release.
The abbreviated environment versions above are compatibility targets, not a
claim of a complete OS image lock. Retain that native baseline with the result.
The bundled Python dependency closure is fully version- and hash-pinned;
dnslib preserves the repository's 0.9.26 pin. Other versions match the validated
executor environment. All six pure wheels came from official PyPI and their
hashes were compared to its release metadata. No apt packages or tools are bundled.

## Source and path substitutions

`resolver_lifecycle.py` imports the shipped resolver module. It calls
`service_files()` and copies its two `BindReadOnlyPaths` directives and all three
`RuntimeDirectory*` directives into dedicated probe services. Rendered source and
probe units are retained in the JSON result. It does not launch K3s or the DNS daemon.

The only resolver path substitutions are:

| Production path | Fixture path |
| --- | --- |
| `/run/sugarkube-ethernet-dns` | `/run/sugarkube-qualification/run/sugarkube-ethernet-dns` |
| `/run/systemd/resolve` | `/run/sugarkube-qualification/run/systemd/resolve` |
| `/etc/resolv.conf` observation | `/run/sugarkube-qualification/etc/resolv.conf` |

The generated runtime directory name is prefixed with
`sugarkube-qualification/run/`. Relative topology and lexical mount ordering are
preserved. Only the runtime and mount directives are exercised; `Type=notify`,
DNS forwarding, actual resolver IPC protocol semantics and K3s startup are not.
Synthetic IPC endpoints use both production socket names but exchange markers.
The production `check_process_view()` still checks the **real guest**
`/etc/resolv.conf` symlink. Preflight requires its exact supported relative target;
this is not validation of the synthetic symlink by that particular guard.
No real guest resolver file is written or bind-mounted.

## Rebuild on ESPC or another connected preparation machine

No private workspace archive is required. Obtain the exact full commit SHA from
this implementation handoff and fetch it through existing repository access.
Do not substitute the moving branch head. Bundle preparation supports Python 3.11
or newer, including the ESPC host's existing Python 3.11.5; no installation is needed.
The **guest runtime remains Python 3.12**. Use the preparation host's existing Python:

```sh
git fetch origin FULL_40_CHARACTER_COMMIT_SHA
git worktree add --detach resolver-qualification-source FULL_40_CHARACTER_COMMIT_SHA
python3 resolver-qualification-source/scripts/qualification/build_resolver_bundle.py \
  --repo resolver-qualification-source --commit FULL_40_CHARACTER_COMMIT_SHA \
  --output resolver-lifecycle-bundle.tar.gz
```

Replace every placeholder with the same exact published commit. The builder reads
source through `git show COMMIT:path`, downloads only pinned official PyPI wheel
URLs, verifies byte counts and SHA256 values against the committed manifest, and
extracts pure dependencies without an installer. The archive includes `deps/`;
the guest needs neither pip nor cached wheels. Tar ordering, ownership, modes,
timestamps and gzip timestamps are normalized. With the same Python/compression
implementation, repeated builds produce identical bytes; per-file SHA256 values
provide the portable comparison across platforms. The manifest records the commit.
All generated manifests use explicit UTF-8 and LF. Checksum and archive member
names use POSIX separators and case-sensitive POSIX ordering on Windows too.

This preparation-only compatibility uses standard-library APIs available in
Python 3.11 and never imports or runs the guest's dependencies. Wheel selection
comes directly from the fixed Linux/Python 3.12 manifest; it does not resolve
Windows dependencies or change any pins. Regression tests cover Windows path
rendering, explicit encoding/newlines and Python 3.11 grammar. Full local build
execution was tested on Python 3.12; this executor has no Python 3.11 or Windows
runtime. An actual ESPC Python 3.11.5 rebuild remains the host-specific validation,
separate from VM execution and requiring no guest or image changes.

## Reviewed future invocation

After separate execution approval, verify the archive hash before extraction and
then verify `SHA256SUMS`. The bundle contains `source/`, `wheels/`, `deps/` and
`python-dependencies.json`. Use paths without spaces or systemd expansion characters.
Image delivery and enabling the supplied boot unit remain separately approved actions.

```sh
cd /opt/resolver-lifecycle-bundle
sha256sum -c SHA256SUMS
python3 source/scripts/qualification/resolver_oneshot.py --run-approved "$PWD"
```

For approved boot delivery, embed `sugarkube-lifecycle-proof.service` in the new
image and enable only that unit. Its fixed bundle path is shown above. It requires
the exact hostname and refuses replay when persistent evidence already exists.
Do not also run the manual invocation. The unit never restarts the wrapper or
escalates to SIGKILL; the wrapper owns its deadlines. The dedicated probe units
also disable SIGKILL escalation and have five-second stop timeouts.

The wrapper sets `SUGARKUBE_RUN_MOUNT_PROOF=1`,
`SUGARKUBE_SKIP_PREINSTALL_TOOLS=1`, `SUGARKUBE_PREINSTALL_TOOL_SHIMS=0`,
`SUGARKUBE_ALLOW_TOOL_SHIMS=0` and `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.
The harness additionally passes `--noconftest` and disables the cache provider.
Exactly two namespace cases must complete, with zero skips/errors/failures.
Missing native tools, unexpected host layout or any skipped test is incomplete
qualification; do not enable shims or install tools to make it pass.

## Cases and evidence

The existing committed namespace test runs first: file-bind negative control,
directory-bind survival, generated atomic publication, IPC recreation, uplink
visibility, read-only writes and namespace cleanup. The lifecycle harness then
exercises systemd's actual generated bindings and preserved runtime directory:

- Host and generated atomic replacements, search original/loss/return, stable mounts.
- Both IPC socket names recreated, changed uplink visible, child-process inheritance.
- Runtime producer stop/start while consumer survives; consumer restart afterward.
- Positive production process-view guard, then writable-mount drift refusal.
- Compatibility-link tamper, unknown host entry, interrupted initialization, and
  recreated directory with retained identity marker: exact guard diagnostics required.
- Independent service cleanup attempts, joined IPC threads, no remaining parent
  mounts or fixture tree, and unchanged real DNS hashes/inodes and network baseline.

Probe units exist only in `/run/systemd/system` and are never enabled. Unit start,
stop and daemon-reload affect this disposable VM only. Failed service cleanup
preserves fixture state; it must never trigger force-unmount or global process kills.
The wrapper rejects boot uptime over five minutes, bounds its own test session to
fifteen minutes, and reserves at most ten minutes for cleanup, all within thirty
minutes of guest boot. Pytest no longer has a parent-only 20-second timeout: its
descendants inherit the wrapper-created session/process group. At timeout or
unexpected parent exit, the wrapper verifies recorded group/session and leader
start-time identity before sending TERM, then waits at most two minutes. It stops
only the two initially absent dedicated probe units. Already removed, inactive
units count as cleaned only after their properties are checked. There is no
host-wide signaling, force-unmount, reboot or hard-stop fallback.

Persistent evidence in `/var/lib/sugarkube-qualification-evidence` includes early
failures, harness output, native/DNS/network baselines, owned process identity,
pre-cleanup state, available JSON/XML results, probe journals and pre-shutdown
process/unit/mount/fixture verification. Missing early XML is a failure, not an
inferred pass. Cleanup scans live process mountinfo for fixture mounts and checks
that no owned processes, units or fixture directories remain before graceful
power-off. Failed or ambiguous cleanup preserves fixtures and leaves the guest
running for owner inspection. JSON evidence is flushed before shutdown; retain
console and disk artifacts too.

After shutdown, independently read those persisted **pre-shutdown** records and
their hashes from disk. Absence of `/run` afterward is not cleanup proof because
that filesystem is volatile. No result means no qualification pass.

Risks are guest-local service/mount leaks, failed shutdown, and fixture mistakes;
NIC-free isolation and no shared storage bound their reach. This stage cannot prove
pod DNS, containerd/kubelet behavior, real resolved DHCP events, migration safety,
or either pinned K3s three-server recovery suite. Those remain separately gated.
