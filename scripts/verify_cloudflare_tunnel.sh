#!/usr/bin/env bash
# Read-only verification for the manually managed staging Cloudflare Tunnel release.
set -Eeuo pipefail

env_name="${1#env=}"
[[ "${env_name}" == staging ]] || { echo "ERROR: Cloudflare Tunnel verification is staging-only." >&2; exit 2; }
expected_context="sugar-staging"
context="$(kubectl config current-context)"
[[ "${context}" == "${expected_context}" ]] || { echo "ERROR: expected context ${expected_context}; got ${context:-<none>}." >&2; exit 3; }

releases="$(helm -n cloudflare list -o json)"
release_count="$(jq '[.[] | select(.name == "cloudflare-tunnel")] | length' <<<"${releases}")"
[[ "${release_count}" == 1 ]] || { echo "ERROR: expected exactly one cloudflare/cloudflare-tunnel Helm release; found ${release_count}." >&2; exit 4; }
[[ "$(jq -r '.[] | select(.name == "cloudflare-tunnel") | .chart' <<<"${releases}")" == "cloudflare-tunnel-0.3.2" ]] || { echo "ERROR: release must use chart cloudflare-tunnel-0.3.2." >&2; exit 4; }

deployment="$(kubectl -n cloudflare get deployment cloudflare-tunnel -o json)"
expected_image='cloudflare/cloudflared:2026.7.3@sha256:e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf'
jq -e --arg image "${expected_image}" '
  .metadata.labels["app.kubernetes.io/managed-by"] == "Helm" and
  .spec.replicas == 2 and
  .spec.strategy.rollingUpdate.maxUnavailable == 0 and
  .spec.strategy.rollingUpdate.maxSurge == 1 and
  .spec.template.spec.affinity.podAntiAffinity.requiredDuringSchedulingIgnoredDuringExecution == [{
    "topologyKey":"kubernetes.io/hostname",
    "labelSelector":{"matchLabels":{
      "app.kubernetes.io/name":"cloudflare-tunnel",
      "app.kubernetes.io/instance":"cloudflare-tunnel"
    }}
  }] and
  .spec.template.spec.containers[0].image == $image and
  (.spec.template.spec.containers[0] | has("livenessProbe") | not) and
  .spec.template.spec.containers[0].readinessProbe.httpGet.path == "/ready" and
  .spec.template.spec.containers[0].readinessProbe.httpGet.port == 2000 and
  .spec.template.spec.containers[0].env == [{"name":"TUNNEL_TOKEN","valueFrom":{"secretKeyRef":{"name":"tunnel-token","key":"token"}}}] and
  (.spec.template.spec.volumes | length) == 0
' <<<"${deployment}" >/dev/null

pods="$(kubectl -n cloudflare get pods -l app.kubernetes.io/name=cloudflare-tunnel,app.kubernetes.io/instance=cloudflare-tunnel -o json)"
jq -e '
  [.items[] | select(
    .metadata.deletionTimestamp == null and
    .status.phase == "Running" and
    any(.status.conditions[]?; .type == "Ready" and .status == "True")
  )] as $ready |
  ($ready | length == 2) and
  all($ready[]; .spec.nodeName | type == "string" and length > 0) and
  ($ready | map(.spec.nodeName) | unique | length == 2)
' <<<"${pods}" >/dev/null
kubectl -n cloudflare get pdb cloudflare-tunnel -o json | jq -e '.spec.minAvailable == 1' >/dev/null
service="$(kubectl -n cloudflare get service cloudflare-tunnel-metrics -o json)"
monitor="$(kubectl -n cloudflare get servicemonitor cloudflare-tunnel -o json)"
jq -e '.spec.type == "ClusterIP" and .spec.selector == {"app.kubernetes.io/instance":"cloudflare-tunnel","app.kubernetes.io/name":"cloudflare-tunnel"} and .spec.ports == [{"name":"metrics","port":2000,"protocol":"TCP","targetPort":2000}]' <<<"${service}" >/dev/null
jq -e '.metadata.labels.release == "kube-prometheus-stack" and .spec.selector.matchLabels == {"app.kubernetes.io/instance":"cloudflare-tunnel","app.kubernetes.io/name":"cloudflare-tunnel"} and .spec.endpoints[0].path == "/metrics"' <<<"${monitor}" >/dev/null

prom_query() {
  local query encoded
  query="$1"
  encoded="$(jq -nr --arg v "${query}" '$v|@uri')"
  kubectl get --raw "/api/v1/namespaces/monitoring/services/http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/query?query=${encoded}"
}
[[ "$(prom_query 'count(up{namespace="cloudflare",service="cloudflare-tunnel-metrics"} == 1)' | jq -r '.data.result[0].value[1] // "0"')" == 2 ]]
[[ "$(prom_query 'count(cloudflared_tunnel_ha_connections{namespace="cloudflare",service="cloudflare-tunnel-metrics"} >= 4)' | jq -r '.data.result[0].value[1] // "0"')" == 2 ]]
[[ "$(prom_query 'count(ALERTS{alertname=~"CloudflareTunnel(NoHealthyConnections|ConnectionsDegraded|MetricsTargetsDown)",alertstate="firing"})' | jq -r '.data.result[0].value[1] // "0"')" == 0 ]]
rules="$(kubectl get --raw '/api/v1/namespaces/monitoring/services/http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/rules?type=alert')"
jq -e '[.data.groups[].rules[] | select(.name == "CloudflareTunnelNoHealthyConnections" or .name == "CloudflareTunnelConnectionsDegraded" or .name == "CloudflareTunnelMetricsTargetsDown") | select(.health == "ok")] | length == 3' <<<"${rules}" >/dev/null
printf '%s\n' 'Cloudflare Tunnel staging verification passed (Secret values were not read).'
