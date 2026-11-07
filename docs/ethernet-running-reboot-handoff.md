# Running-server reboot handoff

This optional source-only extension handles an original server whose Ethernet
address changed while K3s or its workload shims were running. It deliberately
requests an **entire host reboot**, then enters the existing strict
[cold recovery path](ethernet-staged-recovery.md). It does not adopt or freeze
surviving containers. No live reboot, installation, deployment or DHCP drill is
part of the offline implementation or its tests.

## Scope and guarantees

The mode is separately armed. It can reboot a host for **one member's** address
change; it does not require proof that all three addresses changed. It therefore
changes the single-member operational behavior too. A reboot interrupts every
service on that host, including services unrelated to Kubernetes. All three
original hosts may reboot concurrently. There is no availability guarantee.

The retained sources are the original etcd database and WAL, original member and
Node identities, and original persistent storage files. The controller never
resets or replaces them, deletes application data, invokes CRI cleanup, kills
shims, clears network-policy rules, or forces a reboot. The normal OS shutdown and
filesystem recovery still apply. This is not a guarantee that arbitrary application
memory, uncommitted transactions, or pending writes survive. Neither successful
request dispatch nor a changed boot ID means cluster recovery succeeded.

A failed or inactive original K3s service can qualify too, with MainPID and
ControlPID zero and no pending service job. That covers address-loss failures that
already stopped K3s but left shims behind. The exact systemd 255
activating/auto-restart waiting state also qualifies with `Restart=always`,
both PIDs zero and no service job. Queued restarts, start-pre, other activating
states, stopping and unrelated jobs still refuse admission. No stop or job
cancellation is issued.

Both service snapshots must independently qualify. Only two automatic-restart
snapshots may differ in InvocationID; all other fields must match, and the final
snapshot is recorded. Address sampling remains unchanged. The controller holds
both nonblocking local locks: a concurrent staged pre-start fails before starting
K3s. Earlier network/resolver pre-start hooks can still run; the locks fence
staged bootstrap and normal ExecStart, not those earlier hook effects. After dispatch intent is saved, the same-boot fence continues to refuse
startup even if the reboot request fails. A transition before final admission
refuses safely; there is no guarantee that a timer catches an eligible window.
A running service must have the pinned internal K3s executable and a valid current
invocation.

Systemd 255 [service state handling][service-state] maps automatic restart waiting
to activating and clears main/control PID ownership. Its timer subsequently
queues a start job and enters the distinct auto-restart-queued state.

[service-state]: https://github.com/systemd/systemd/blob/v255/src/core/service.c

## Why reboot instead of container adoption or freezing

The exact K3s releases both install `KillMode=process` and `Delegate=yes`:
[v1.34.5+k3s1](https://github.com/k3s-io/k3s/blob/v1.34.5%2Bk3s1/install.sh) and
[v1.35.4+k3s1](https://github.com/k3s-io/k3s/blob/v1.35.4%2Bk3s1/install.sh).
Stopping the main service is not a proof that pod shims or pod cgroups vanished.
The embedded containerd process is tied to K3s through `exec.CommandContext` and
its death-signal handling. The generated kill-all script additionally kills shim
process trees, unmounts runtime/pod paths, removes CNI state and interfaces, and
filters firewall rules. None of those broad effects is used here.

The pinned containerd releases have identical relevant recovery logic:
[v2.1.5-k3s1](https://github.com/k3s-io/containerd/blob/v2.1.5-k3s1/internal/cri/server/restart.go)
and
[v2.2.3-k3s1](https://github.com/k3s-io/containerd/blob/v2.2.3-k3s1/internal/cri/server/restart.go).
Running tasks can be adopted, but interrupted Created/Stopped tasks can be deleted
with process termination, and orphan runtime directories can be cleaned up.
Unexpected task states become unknown. A freezer is not a supported restore
barrier, and normal K3s starts kubelet lifecycle handling alongside networking.
An earlier PID snapshot cannot prove safe adoption across concurrent pod creation.
This extension leaves the cold path's residual-process refusal intact instead of
turning it into a permissive shim list.

## Exact systemd boundary

The initial supported host version is **systemd 255**, with the installed
`/usr/bin/systemctl` and `/usr/bin/timeout` binaries pinned in the opt-in.
The [v255 reboot implementation](https://github.com/systemd/systemd/blob/v255/src/systemctl/systemctl-start-special.c)
is asynchronous through logind or a normal target job. A zero exit status is only
request acceptance. A timeout, interruption, inhibitor or error retains the
pre-dispatch intent and never causes a retry or force fallback by this controller.

The single requested command is:

```text
/usr/bin/systemctl --no-block --no-wall --check-inhibitors=yes reboot
```

The explicit inhibitor option matters: v255's
[inhibitor check](https://github.com/systemd/systemd/blob/v255/src/systemctl/systemctl-logind.c)
otherwise defaults to skipping checks for root/noninteractive callers. No
`--force`, ignored-inhibitor option, kernel reboot syscall, scheduled fallback or
repeated command is issued. Standard systemd/logind shutdown behavior remains;
this does not promise application-aware flushing.

The [v255 job listing](https://github.com/systemd/systemd/blob/v255/src/systemctl/systemctl-list-jobs.c)
is a plain four-column table, not JSON. Admission uses no-legend, no-pager, plain,
full output and rejects unrecognized rows. The sole possible exemption is the
current recovery watcher's own start/running job. Its exact installed and loaded
unit, job ID, invocation, cgroup, timeout parent and Python child arguments must
all match. In [v255 service startup](https://github.com/systemd/systemd/blob/v255/src/core/service.c),
a oneshot ExecStart is the main process, so the expected MainPID is the `timeout`
parent, not the Python child. An arbitrary process or similarly named service
cannot claim this exemption.

## Durable lifecycle

1. Validate the original enrollment, machine/database identity, runtime hashes,
   scoped resolver, migration fence and eligible original service. Observe the
   same new Ethernet address for at least 30 seconds within a 300-second window.
   Managed network YAML may still contain the known prior address while the server
   runs. Accept only the exact managed file for that prior address or the current
   address, bind its hash to the observation, and never refresh it here. Reject
   mixed, unexpected or changed content. Recheck stable address, local mDNS, YAML,
   boot ID and service identity before dispatch.
2. Refuse any unfinished membership, Node-address or staged recovery incident.
   Persist and fsync `reboot-handoff.json` with a fresh incident ID, original boot
   ID, old/new address, enrollment hash and original identities before the one
   reboot request. Record request acceptance separately if the command returns.
3. Every same-boot invocation retains that intent and refuses another request.
   A startup on a new boot must still prove the same address, enrollment and
   database, current-address YAML from the ordinary network pre-start hook, old
   completed incident evidence, and strict absence of residual
   runtime consumers before recording cold authorization.
4. Before the cold controller launches its bootstrap child, bind the reboot
   handoff to both the exact new staged ID and planned membership incident ID.
   An interrupted consumed authorization is not reusable. Only an unbound
   authorization, for which no bootstrap could have launched, may repeat the
   same-boot quiet and old-evidence proof.
5. Finish the existing original-member recovery, Node checks and workload/HTTPS
   verification. Mark the reboot incident complete only when its linked staged
   record is normal and its linked membership incident is complete. A boot change
   or an unrelated complete journal is insufficient.
6. A genuinely later address change after full completion archives the previous
   reboot evidence before recording a new request. That is a new external
   incident, not replay of the earlier request. A previous request from the same
   origin boot cannot be submitted again. There is no reboot retry loop.

No intent-clearing, generic resume, inhibitor override, force or cleanup command
is provided. Failed requests remain latched even if the host still appears normal.
An inhibited or rejected request stays latched even after its inhibitor disappears;
operator reconciliation is required. A DHCP change across the reboot, another reboot during cold recovery, changed
identity, failed persistence or incomplete staged work requires investigation.

## Separate opt-in and artifacts

The existing staged opt-in is extended with exactly:

```json
"reboot_handoff": {
  "schema_version": 1,
  "whole_host_reboot": true,
  "systemd_major": 255
}
```

Its `runtime_sha256` map must additionally include the installed
`ethernet_reboot_handoff.py`, `/usr/bin/systemctl` and `/usr/bin/timeout`.
Existing cold-only opt-ins remain valid without these fields. A pending reboot
marker blocks startup if its opt-in is removed. The helper is imported only after
backend fingerprint validation.

The new artifact command prints, but does not install, the explicitly armed
watcher service:

```sh
python3 scripts/ethernet_staged_recovery.py running-service
```

It replaces the owned recovery service with the `watch-running` entry point. The
existing timer and startup hook need no new activation mechanism. Installation,
reloading, enabling and actual reboots remain separate operational actions.
Simply adding the source files does not arm a host. Without an active reboot
intent, ordinary cold address-change startup still uses the original cold path.

## Offline evidence and remaining qualification

Tests model all three one-shot requests, changed boots, exact linked cold recovery,
unchanged/second incidents, failed requests, clock/address changes, residual
consumers, ordinary cold startup with the option enabled, runtime/tool pins and
systemd oneshot job ownership. They never execute systemd or reboot a machine.

Live qualification still needs both exact K3s releases on the supported systemd
host: running-address loss, already-failed K3s with residual shims, one-member and
all-member transitions, inhibitor refusal, delayed/failed shutdown, actual reboot,
address changes during boot, repeated completed incidents, original committed
markers and persistent storage, and final workload/HTTPS convergence. Other
systemd versions and nonstandard service layouts remain unsupported.
