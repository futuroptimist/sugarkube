# Staging ingress HA source of truth

These two `HelmChartConfig` resources customize the K3s-packaged `coredns` and
`traefik` charts. K3s owns their `HelmChart` resources and all generated manifests;
this directory owns only the supported values overlay. Do not copy these resources
into the legacy Flux kustomization or edit `/var/lib/rancher/k3s/server/manifests`.

The checked-in rollback values deliberately restore the previous singleton
configuration. Use only the guarded `just staging-ingress-ha-*` commands described
in the operations runbook.
