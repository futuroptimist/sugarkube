# 2026-07-29 staging node-failure drill

## Scope and limitations

> **Important:** The serial sampler cannot prove that no failures occurred between samples. This
> drill demonstrated continuity of the shared ingress and DNS platform, not fast rescheduling of
> every singleton workload. token.place happened to remain on a surviving node. PagerDuty detected
> the incident, but this evidence does **not** establish PagerDuty auto-resolution timing.

This is the durable, sanitized record of the staging drill completed on July 29, 2026. Before
[PR #2400](https://github.com/futuroptimist/sugarkube/pull/2400), staging ran one CoreDNS replica,
one Traefik replica, and two Cloudflare Tunnel replicas. A previous loss of `sugarkube3` interrupted
public token.place service for roughly six minutes. PR #2400 added node-spread CoreDNS coverage and
two node-separated Traefik replicas.

## Observations

The operator manually powered off `sugarkube3` at approximately
`2026-07-29T00:05:25-07:00`. No additional node shutdown is required to use this record.

* `sugarkube3` became `NotReady`; `sugarkube4` and `sugarkube5` remained `Ready`. Kubernetes API
  readiness, including its etcd dependency, remained available.
* Healthchecks detected the missing node heartbeat and created a PagerDuty incident. No
  auto-resolution time is claimed.
* Sampled DSPACE, danielsmith.io, and Jobbot3000 endpoints remained HTTP 200.
* token.place stayed on `sugarkube4` with zero restarts. It had the only visible transient: one
  root request took about 4.7 seconds, one `/livez` request took about 10 seconds, and one
  `/healthz` request returned HTTP 502 after about 10 seconds. Samples were normal again by about
  `00:06:14`, less than 49 seconds after shutdown. The compute client needed roughly another
  10–15 seconds to re-register before chat worked.
* EndpointSlices eventually marked the dead-node Traefik and CoreDNS endpoints `ready:false`,
  `serving:false`, and `terminating:true`, while surviving endpoints stayed ready and serving. A
  replacement Traefik pod later scheduled on `sugarkube5`.

After power restoration, all nodes returned to `Ready`. CoreDNS had ready endpoints on all three
nodes, and Traefik was ready on `sugarkube4` and `sugarkube5`. Ingress HA, blackbox, Prometheus,
Alertmanager, and node-heartbeat verification passed, and Healthchecks returned green.

## Conclusions

The changed shared DNS/ingress topology kept sampled public services available through a one-node
failure and recovered its intended spread. The token.place transient and compute-client
re-registration show why that platform conclusion must not be generalized to uninterrupted or
fast-rescheduled singleton applications. Residual transient investigation is tracked in
[issue #2407](https://github.com/futuroptimist/sugarkube/issues/2407).
