# Staged original-server recovery

This source-only, separately opted-in controller extends recovery to a **cold or
already quiesced** three-server cluster whose original Ethernet addresses all
changed. It has offline model and adapter tests, not live qualification. Do not
install, reload, start, or perform DHCP drills on a cluster based on this document
without separate operational approval. Existing version 2 behavior is unchanged.

## Why a separate startup phase is needed

Both supported exact releases have the same relevant ordering:

- [v1.34.5+k3s1 server](https://github.com/k3s-io/k3s/blob/v1.34.5%2Bk3s1/pkg/cli/server/server.go)
  and [v1.35.4+k3s1 server](https://github.com/k3s-io/k3s/blob/v1.35.4%2Bk3s1/pkg/cli/server/server.go)
  route `--disable-agent` to `agent.RunStandalone` instead of `agent.Run`.
- [v1.34.5+k3s1 agent](https://github.com/k3s-io/k3s/blob/v1.34.5%2Bk3s1/pkg/agent/run.go)
  and [v1.35.4+k3s1 agent](https://github.com/k3s-io/k3s/blob/v1.35.4%2Bk3s1/pkg/agent/run.go)
  do not run kubelet, containerd or CNI in that standalone path. Normal-agent
  networking errors request shutdown of the server process.
- [v1.34.5+k3s1 etcd](https://github.com/k3s-io/k3s/blob/v1.34.5%2Bk3s1/pkg/etcd/etcd.go)
  and [v1.35.4+k3s1 etcd](https://github.com/k3s-io/k3s/blob/v1.35.4%2Bk3s1/pkg/etcd/etcd.go)
  use `CurrentETCDOptions` and `cluster(..., false, ...)` when the original WAL
  exists. Their `Test` also requires the current numeric peer URL. Thus membership
  repair must precede waiting for API readiness, even after hostname transport
  restores consensus.

The controller never changes the original server command, database, WAL, member
identity, trust roots, credentials or network-policy configuration. The temporary
child receives only the extra `--disable-agent=true` argument. Its environment is
reconstructed from the verified service configuration, not the invoking shell.
It never disables admission webhooks or changes egress-selector settings. A webhook
that cannot function without workloads is a blocker, not permission to bypass it.

## Lifecycle and failure boundary

`scripts/ethernet_staged_recovery.py` provides a synchronous systemd pre-start
coordinator. Its original-database child stays in the service's own cgroup and
must exit before pre-start returns. It is not an orphaned pre-start daemon.

1. Verify the armed enrollment, original database identities, pinned binaries and
   helper files, original service configuration and scoped resolver. Require the
   actual current service control PID, invocation and cgroup. Refuse residual K3s,
   etcd, kubelet, containerd, shim or pod-cgroup processes. No process is killed to
   achieve this precondition.
2. Persist bootstrap-start intent before launching the exact original K3s binary.
   Hold an inherited local lease while the child lives. Validate the child's actual
   resolver mount view before authenticated etcd or API proofs.
3. Restore original hostname peer transport. Use the existing etcd-only guarded
   membership protocol to repair each member's numeric URL while retaining its
   enrolled hostname. No API or Ready condition is required at this stage.
4. Once all original members have current numeric URLs, wait for authenticated
   APIs. Acquire the existing global membership lock for the local Node repair and
   process handover. Keep that ownership throughout conditional annotation/status
   patches, independent readbacks, child stop and normal-agent startup. Serializing
   Node repair together with handover prevents another bootstrap stopping midway
   through a patch readback. No Ready conditions or workloads are fabricated.
5. Send SIGTERM only to the owned child and wait at most 60 seconds. Require a clean
   exit, no residual runtime processes, both original surviving voters, exact lock
   ownership and fresh address readbacks. Persist normal-start intent, then return
   to the unchanged ordinary systemd ExecStart.
6. The staged post-start hook waits up to 120 seconds for original quorum, current
   addresses, a fresh local Ready heartbeat and the ordinary K3s service process.
   It releases only its exact lock. Full cluster/workload/HTTPS completion can still
   be pending while the other two servers finish. That pending state does not fail
   the successfully completed handover.

The startup window is 900 seconds; bootstrap polling is bounded at 600 seconds.
The service stop timeout is 75 seconds and forced SIGKILL is disabled by the
explicit staged hook. An unresponsive child remains a blocked service requiring
operator investigation. A failed normal-start proof retains global ownership and
fails the service hook; it never hands the lock to another member blindly.

Only read-only availability proofs may reconnect. Confirmed lock contention can
wait. Uncertain writes, interrupted lifecycle intent, unknown acquisition/release,
failed stop, changed identities and incomplete previous incidents remain latched.
SIGTERM cleanup records its own durable intent and retains the failed phase. There
is deliberately no generic resume, force, reset, clear-journal or lock-stealing
command. Preserve journals and investigate rather than deleting them.

After full prior workload completion, an unchanged simultaneous cold restart does
not require live survivor APIs. A later address incident first archives the prior
staged, membership and verified address journals together, then starts a new
incident. A second change before full completion is refused.

## Explicit opt-in and installation artifacts

The runtime does not install files, enable a timer, reload systemd or start a
service. It emits two reviewable artifacts:

```sh
python3 scripts/ethernet_staged_recovery.py hook
python3 scripts/ethernet_staged_recovery.py completion-service
```

The hook is a replacement for the existing owned
`30-sugarkube-quorum-recovery.conf`, not an additional hook. The completion service
is a replacement for `sugarkube-ethernet-recovery.service`; the existing timer may
invoke it after separately approved installation. Old version 2 commands will
reject the replaced hook rather than silently adopting this architecture.

Both releases use the Linux launcher's `syscall.Exec` to replace the outer
`/usr/local/bin/k3s` with the extracted internal server executable. Both the
bootstrap PID and the normal service PID must resolve to the enrolled internal
binary. The outer launcher is allowed only during a bounded 30-second initial
exec transition. Neither a matching process name nor the launcher hash alone
proves the internal executable's identity.

The root-owned `/etc/rancher/k3s/sugarkube-staged-recovery.json` opt-in contains:

- `schema_version: 1` and `cold_original_database_bootstrap: true`;
- `enrollment_sha256`: the SHA-256 of the exact existing armed version 2 enrollment;
- `server_executable`: the canonical, non-symlink extracted executable path,
  `/var/lib/rancher/k3s/data/<64-character lowercase hexadecimal digest>/bin/k3s`;
- `runtime_sha256`: a map with exactly the installed staged runtime, original
  hyphenated `ethernet-quorum-recover.py`, `/usr/local/bin/k3s`,
  `ethernet_etcd_grpc.py`, `ethernet-etcd.desc`, `ethernet_wal_identity.py` and
  `ethernet_mdns_resolver.py`, and the exact `server_executable` paths mapped to
  their SHA-256 values.

Only the directory-based resolver enrollment is accepted. The base enrollment's
machine, configuration and trust fingerprints are retained, not regenerated to
conceal drift. All pinned files must have trusted root ownership and parents.
When the shared migration guard is available, staged operations call its
read-only `watch` mode, never consuming a migration one-start permit. Otherwise,
any migration intent or completion marker, including a dangling symlink, blocks
this runtime. The installation/migration procedure must preserve the existing journals and
install prerequisites before exposing the replacement hook. This document does
not authorize that operational transition.

`check-completion` performs the original full-cluster readiness checks after
handover. It refuses a running address change without stopping or restarting any
service. A running server may retain pod shims even after its main K3s process
stops, so this implementation does **not** claim unattended running-churn recovery.
Cold/quiesced admission and live DHCP behavior remain distinct qualification cases.
The separately armed [whole-host reboot handoff](ethernet-running-reboot-handoff.md)
provides a defined running-host mode; it is not enabled by this cold-only opt-in.

## Required qualification

Offline tests cover three coordinated original-member starts, membership-before-API
ordering, conditional Node patches, serialized handover, old identity preservation,
unknown outcomes, bounded child stop, isolated-Python imports, verified child
configuration, resolver process views and subsequent incidents. They do not run
K3s, systemd or cluster operations.

Separate live qualification on both exact releases must establish actual service
PID/executable behavior, clean SIGTERM exit, resolver namespaces, original member
and Node identities, committed data markers, full workload and HTTPS convergence,
restart persistence, power interruption, unavailable peers, failed admission,
residual-shim refusal and repeated completed address incidents. No production
readiness or permission to deploy is implied by the offline results.
