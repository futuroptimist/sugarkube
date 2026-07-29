# 2026-07-29 staging node-failure drill

## Context and change

Before PR #2400, staging ran one CoreDNS replica, one Traefik replica, and two Cloudflare Tunnel
replicas. Losing `sugarkube3` caused roughly six minutes of public token.place interruption. PR
#2400 added node-spread CoreDNS coverage and two node-separated Traefik replicas.

For the post-change drill, an operator manually powered off `sugarkube3` at approximately
`2026-07-29T00:05:25-07:00`. No shutdown is required to use this record, and this report contains no
credentials, Secret data, private certificate material, raw event dump, or unnecessary private IP.

## Observations

* `sugarkube3` became `NotReady`; `sugarkube4` and `sugarkube5` stayed `Ready`. Kubernetes API and
  etcd readiness remained available.
* Healthchecks detected the missing node heartbeat and created a PagerDuty incident. This evidence
  does not establish PagerDuty auto-resolution timing, so none is claimed.
* Sampled DSPACE, danielsmith.io, and Jobbot3000 endpoints remained HTTP 200.
* token.place remained on `sugarkube4` with zero restarts. It showed the only visible transient: one
  root request took about 4.7 seconds, one `/livez` request took about 10 seconds, and one `/healthz`
  request returned HTTP 502 after about 10 seconds. Sampled endpoints were normal again by
  approximately `00:06:14`, less than 49 seconds after shutdown. The compute client needed roughly
  another 10–15 seconds to re-register before chat worked.
* EndpointSlices eventually marked dead-node Traefik and CoreDNS endpoints `ready:false`,
  `serving:false`, and `terminating:true`; surviving endpoints stayed ready and serving. A replacement
  Traefik pod later scheduled on `sugarkube5`.
* After restoration, all nodes became `Ready`. CoreDNS had ready endpoints on all three nodes;
  Traefik was ready on `sugarkube4` and `sugarkube5`. Ingress HA, blackbox, Prometheus, Alertmanager,
  and node-heartbeat verification passed, and Healthchecks returned green.

## Conclusions and limitations

> **Limitations:** The sampler was serial and cannot prove zero failures between samples. This drill
> proved continuity of shared ingress and DNS, not fast rescheduling of every singleton workload.
> token.place happened to remain on a surviving node. Platform continuity must not be presented as
> evidence that every application is highly available.

The results support the narrower conclusion that the post-PR #2400 shared DNS and ingress topology
continued serving sampled traffic through this one-node loss. They also preserve evidence of a
short token.place transient and slower compute-client recovery. Residual-transient investigation is
tracked in [issue #2407](https://github.com/futuroptimist/sugarkube/issues/2407).

The default control-plane readiness check is:

```bash
kubectl get --raw='/readyz?verbose' | rg 'etcd|readyz check passed'
```

It proves that the contacted API server is ready and that this API server's etcd dependency is
ready. It is not a complete per-member etcd health, consistency, or latency report. Optional deeper
inspection requires a separately installed compatible `etcdctl` configured with official
K3s-managed endpoints and client-certificate paths; never print certificate, key, or Secret
contents.
