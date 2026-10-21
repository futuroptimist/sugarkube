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
cleanup and graceful shutdown. The reviewed one-shot boot wrapper must record
progress and preserve failure evidence. No reboot, hard power-off, credential
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

## Reviewed future invocation

After separate execution approval, transfer and verify `SHA256SUMS` before
extracting or running anything. The bundle contains `source/`, `wheels/`, and
`python-dependencies.json`. Use paths without spaces or systemd expansion characters.
The preparation helper only verifies/unpacks pure wheels into a fresh private
directory; it does not invoke pip, install system packages or run the harness.

```sh
cd /opt/resolver-lifecycle-bundle
sha256sum -c SHA256SUMS
python3 source/scripts/qualification/resolver_offline_prepare.py "$PWD" "$PWD/deps"
export PYTHONPATH="$PWD/deps"
export SUGARKUBE_RUN_MOUNT_PROOF=1
export SUGARKUBE_SKIP_PREINSTALL_TOOLS=1
export SUGARKUBE_PREINSTALL_TOOL_SHIMS=0
export SUGARKUBE_ALLOW_TOOL_SHIMS=0
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
python3 source/scripts/qualification/resolver_lifecycle.py --run-approved "$PWD/result.json"
```

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
The boot wrapper must retain console output, native baseline, JSON/XML results,
unit journals and artifact hashes, then verify cleanup from the powered-off disk
after a successful graceful shutdown. No result means no qualification pass.

Risks are guest-local service/mount leaks, failed shutdown, and fixture mistakes;
NIC-free isolation and no shared storage bound their reach. This stage cannot prove
pod DNS, containerd/kubelet behavior, real resolved DHCP events, migration safety,
or either pinned K3s three-server recovery suite. Those remain separately gated.
