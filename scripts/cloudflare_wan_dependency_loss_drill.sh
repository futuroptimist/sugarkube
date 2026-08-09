#!/usr/bin/env bash
# Deterministic, process-preserving Cloudflare WAN dependency-loss drill.
set -Eeuo pipefail

readonly EXPECTED_CONTEXT=sugar-staging EXPECTED_REVISION=2
readonly EXPECTED_IMAGE='cloudflare/cloudflared:2026.7.3@sha256:e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf'
readonly SELECTOR='app.kubernetes.io/name=cloudflare-tunnel,app.kubernetes.io/instance=cloudflare-tunnel'
readonly CONFIRM='INTERRUPT BOTH STAGING CLOUDFLARE CONNECTORS'
readonly ENDPOINTS=(
  https://staging.democratized.space/ https://staging.democratized.space/config.json
  https://staging.democratized.space/healthz https://staging.democratized.space/livez
  https://staging.token.place/ https://staging.token.place/healthz
  https://staging.token.place/livez https://staging.token.place/api/v1/meta
  https://staging.danielsmith.io/ https://staging.danielsmith.io/healthz
  https://staging.danielsmith.io/livez https://staging.jobbot3000.tech/
  https://staging.jobbot3000.tech/healthz https://staging.jobbot3000.tech/livez
  https://staging.jobbot3000.tech/tracker https://staging.jobbot3000.tech/manifest.webmanifest
)

execute=0 env_name= approved_revision= confirmation= evidence_dir=
usage() { cat <<'EOF'
Usage: cloudflare_wan_dependency_loss_drill.sh [--execute] --env staging
       [--approved-revision COMMIT] [--confirm 'INTERRUPT BOTH STAGING CLOUDFLARE CONNECTORS']

The default is a non-mutating plan. Execution additionally requires WAN_DRILL_NODE_EXEC,
an operator-reviewed executable invoked as: NODE_EXEC <node> <root-command>.
EOF
}
while (($#)); do
  case "$1" in
    --execute) execute=1; shift ;;
    --env) env_name=${2-}; shift 2 ;;
    --approved-revision) approved_revision=${2-}; shift 2 ;;
    --confirm) confirmation=${2-}; shift 2 ;;
    --evidence-dir) evidence_dir=${2-}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; exit 2 ;;
  esac
done

owner="sugarkube-cfwan-$(date -u +%Y%m%dT%H%M%SZ)-$$"
table="${owner//-/_}"
cleanup_required=0
declare -a pods=() uids=() nodes=() restarts=() sandboxes=() netns=() installed=()

node_exec() { "${WAN_DRILL_NODE_EXEC}" "$1" "$2"; }
cleanup_command() {
  printf 'nsenter --net=/proc/%q/ns/net nft delete table inet %q' "$2" "$table"
}
cleanup() {
  local rc=${1:-$?} i failed=0 cmd
  trap - EXIT INT TERM
  if ((cleanup_required)); then
    for i in "${!installed[@]}"; do
      [[ ${installed[$i]} == 1 ]] || continue
      cmd=$(cleanup_command "${nodes[$i]}" "${netns[$i]}")
      if ! node_exec "${nodes[$i]}" "$cmd"; then
        failed=1; printf 'MANUAL CLEANUP (%s): %s\n' "${nodes[$i]}" "$cmd" >&2
      fi
    done
  fi
  ((failed == 0)) || { echo 'ERROR: automated cleanup could not be proven.' >&2; exit 90; }
  exit "$rc"
}
trap 'cleanup $?' EXIT
trap 'cleanup 130' INT
trap 'cleanup 143' TERM

if ((execute == 0)); then
  cat <<EOF
PLAN ONLY (no cluster or node commands were run)
Mechanism: create a uniquely named nftables inet table in each selected pod network namespace;
drop that namespace's OUTPUT traffic, including established QUIC, without signaling cloudflared.
Before disruption, install an independent 210-second transient-systemd cleanup watchdog per node.
Only the exact owner table is deleted. No ruleset is flushed. Execution remains blocked until every
preflight succeeds and an authenticated WAN_DRILL_NODE_EXEC adapter is supplied.
Owner example: ${owner}
EOF
  exit 0
fi

[[ $env_name == staging ]] || { echo 'ERROR: execution is staging-only.' >&2; exit 3; }
[[ $(kubectl config current-context) == "$EXPECTED_CONTEXT" ]] || { echo "ERROR: expected context ${EXPECTED_CONTEXT}." >&2; exit 4; }
[[ -n $approved_revision && $(git rev-parse HEAD) == "$approved_revision" ]] || { echo 'ERROR: HEAD is not the explicitly approved revision.' >&2; exit 5; }
[[ -z $(git status --porcelain) ]] || { echo 'ERROR: repository tree is dirty.' >&2; exit 6; }
[[ $confirmation == "$CONFIRM" ]] || { echo "ERROR: confirmation must exactly equal: ${CONFIRM}" >&2; exit 7; }
[[ -n ${WAN_DRILL_NODE_EXEC:-} && -x ${WAN_DRILL_NODE_EXEC:-/nonexistent} ]] || { echo 'ERROR: WAN_DRILL_NODE_EXEC must name an operator-reviewed executable.' >&2; exit 8; }

releases=$(helm -n cloudflare list -o json)
jq -e --argjson rev "$EXPECTED_REVISION" '[.[]|select(.name=="cloudflare-tunnel" and .status=="deployed" and .revision==$rev)]|length==1' <<<"$releases" >/dev/null || { echo 'ERROR: expected exactly one deployed Helm release at revision 2.' >&2; exit 9; }
deployment=$(kubectl -n cloudflare get deployment cloudflare-tunnel -o json)
jq -e --arg image "$EXPECTED_IMAGE" '.metadata.labels["app.kubernetes.io/managed-by"]=="Helm" and .metadata.labels["app.kubernetes.io/name"]=="cloudflare-tunnel" and .metadata.labels["app.kubernetes.io/instance"]=="cloudflare-tunnel" and .spec.template.spec.containers[0].image==$image' <<<"$deployment" >/dev/null || { echo 'ERROR: Deployment labels or immutable image differ.' >&2; exit 10; }
pods_json=$(kubectl -n cloudflare get pods -l "$SELECTOR" -o json)
mapfile -t rows < <(jq -r --arg image "$EXPECTED_IMAGE" '[.items[]|select(.metadata.deletionTimestamp==null and .status.phase=="Running" and any(.status.conditions[]?;.type=="Ready" and .status=="True") and .metadata.labels["app.kubernetes.io/name"]=="cloudflare-tunnel" and .metadata.labels["app.kubernetes.io/instance"]=="cloudflare-tunnel" and .spec.containers[0].image==$image)]|.[]|[.metadata.name,.metadata.uid,.spec.nodeName,(.status.containerStatuses[0].restartCount|tostring),.status.containerStatuses[0].containerID]|@tsv' <<<"$pods_json")
[[ ${#rows[@]} == 2 ]] || { echo 'ERROR: exactly two Ready release pods are required.' >&2; exit 11; }
for row in "${rows[@]}"; do IFS=$'\t' read -r p u n r s <<<"$row"; pods+=("$p"); uids+=("$u"); nodes+=("$n"); restarts+=("$r"); sandboxes+=("$s"); done
[[ ${nodes[0]} != "${nodes[1]}" ]] || { echo 'ERROR: connectors must be on distinct nodes.' >&2; exit 12; }

prom() { kubectl get --raw "/api/v1/namespaces/monitoring/services/http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/query?query=$(jq -nr --arg q "$1" '$q|@uri')" | jq -r '.data.result[0].value[1]//"0"'; }
[[ $(prom 'count(up{namespace="cloudflare",service="cloudflare-tunnel-metrics"} == 1)') == 2 && $(prom 'count(cloudflared_tunnel_ha_connections{namespace="cloudflare",service="cloudflare-tunnel-metrics"} >= 4)') == 2 ]] || { echo 'ERROR: Prometheus targets or HA connections unhealthy.' >&2; exit 13; }
[[ $(prom 'count(ALERTS{alertname=~"CloudflareTunnel.*",alertstate="firing"})') == 0 ]] || { echo 'ERROR: active Cloudflare alert.' >&2; exit 14; }
printf '' >"${TMPDIR:-/tmp}/${owner}-endpoints"
for url in "${ENDPOINTS[@]}"; do code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "$url"); printf '%s\t%s\n' "$url" "$code" >>"${TMPDIR:-/tmp}/${owner}-endpoints"; [[ $code == 200 ]] || { echo "ERROR: unhealthy endpoint: $url" >&2; exit 15; }; done

mkdir -p "${evidence_dir:=${HOME}/operator-evidence/cloudflare-wan-dependency-loss-drill-${owner}}"; chmod 700 "$evidence_dir"
# Metadata only: kubectl never requests Secret data; jsonpath selects metadata explicitly.
helm -n cloudflare history cloudflare-tunnel -o json >"$evidence_dir/helm-before.json"
kubectl -n cloudflare get secret tunnel-token -o 'jsonpath={.metadata.uid}{"\t"}{.metadata.resourceVersion}{"\n"}' >"$evidence_dir/secret-before.tsv"
kubectl -n cloudflare get deployment cloudflare-tunnel -o json >"$evidence_dir/deployment-before.json"
printf '%s\n' "${rows[@]}" >"$evidence_dir/pods-before.tsv"
cp "${TMPDIR:-/tmp}/${owner}-endpoints" "$evidence_dir/endpoints-before.tsv"
printf 'targets=2\nha_pods=2\nalerts=0\n' >"$evidence_dir/metrics-before.txt"
rm -f "${TMPDIR:-/tmp}/${owner}-endpoints"

for i in 0 1; do
  # The adapter must resolve the exact container sandbox to one live netns PID and reject ambiguity.
  pid=$(node_exec "${nodes[$i]}" "crictl inspect '${sandboxes[$i]#*://}' -o json | jq -er '.info.pid|select(type==\"number\" and .>1)'") || { echo 'ERROR: exact pod network namespace could not be resolved.' >&2; exit 16; }
  [[ $pid =~ ^[0-9]+$ ]] || { echo 'ERROR: invalid network namespace PID.' >&2; exit 16; }; netns+=("$pid")
  check="nsenter --net=/proc/${pid}/ns/net nft list table inet ${table}"
  node_exec "${nodes[$i]}" "$check" >/dev/null 2>&1 && { echo 'ERROR: owner-tagged rule already exists.' >&2; exit 17; }
done
printf '%s\n' "${netns[@]}" >"$evidence_dir/netns-pids.tsv"

cleanup_required=1; installed=(0 0)
for i in 0 1; do
  delete=$(cleanup_command "${nodes[$i]}" "${netns[$i]}")
  watchdog="systemd-run --quiet --unit '${owner}-cleanup' --on-active=210s /bin/sh -c '${delete}'"
  node_exec "${nodes[$i]}" "$watchdog" || { echo 'ERROR: cleanup watchdog installation failed.' >&2; exit 18; }
  add="nsenter --net=/proc/${netns[$i]}/ns/net nft add table inet ${table}; nsenter --net=/proc/${netns[$i]}/ns/net nft add chain inet ${table} output '{ type filter hook output priority -300; policy drop; comment \"${owner}\"; }'"
  node_exec "${nodes[$i]}" "$add" || { echo 'ERROR: disruption setup failed.' >&2; exit 19; }; installed[$i]=1
done

deadline=$((SECONDS+120))
while ((SECONDS < deadline)); do
  now=$(kubectl -n cloudflare get pods -l "$SELECTOR" -o json)
  unchanged=$(jq -r --arg u0 "${uids[0]}" --arg u1 "${uids[1]}" --argjson r0 "${restarts[0]}" --argjson r1 "${restarts[1]}" '[.items[]|select((.metadata.uid==$u0 and .status.containerStatuses[0].restartCount==$r0) or (.metadata.uid==$u1 and .status.containerStatuses[0].restartCount==$r1))]|length' <<<"$now")
  [[ $unchanged == 2 ]] || { echo 'ERROR: pod UID changed or cloudflared restarted.' >&2; exit 20; }
  ready=$(jq '[.items[]|select(any(.status.conditions[]?;.type=="Ready" and .status=="True"))]|length' <<<"$now")
  [[ $ready == 0 && $(prom 'sum(cloudflared_tunnel_ha_connections{namespace="cloudflare",service="cloudflare-tunnel-metrics"})') == 0 ]] && break
  sleep 5
done
[[ ${ready:-2} == 0 ]] || { echo 'ERROR: interruption was not proven; NetworkPolicy-only results never pass.' >&2; exit 21; }
for i in 0 1; do node_exec "${nodes[$i]}" "$(cleanup_command "${nodes[$i]}" "${netns[$i]}")"; installed[$i]=0; done; cleanup_required=0

deadline=$((SECONDS+300)); recovered=0
while ((SECONDS < deadline)); do
  now=$(kubectl -n cloudflare get pods -l "$SELECTOR" -o json)
  same=$(jq -r --arg u0 "${uids[0]}" --arg u1 "${uids[1]}" --argjson r0 "${restarts[0]}" --argjson r1 "${restarts[1]}" '[.items[]|select((.metadata.uid==$u0 and .status.containerStatuses[0].restartCount==$r0) or (.metadata.uid==$u1 and .status.containerStatuses[0].restartCount==$r1))|select(any(.status.conditions[]?;.type=="Ready" and .status=="True"))]|length' <<<"$now")
  [[ $same == 2 && $(prom 'count(cloudflared_tunnel_ha_connections{namespace="cloudflare",service="cloudflare-tunnel-metrics"} >= 4)') == 2 ]] && { recovered=1; break; }; sleep 5
done
[[ $recovered == 1 ]] || { echo 'ERROR: same-process recovery was not proven.' >&2; exit 22; }
for url in "${ENDPOINTS[@]}"; do [[ $(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "$url") == 200 ]] || exit 23; done
diff -u "$evidence_dir/helm-before.json" <(helm -n cloudflare history cloudflare-tunnel -o json)
diff -u "$evidence_dir/secret-before.tsv" <(kubectl -n cloudflare get secret tunnel-token -o 'jsonpath={.metadata.uid}{"\t"}{.metadata.resourceVersion}{"\n"}')
diff -u "$evidence_dir/deployment-before.json" <(kubectl -n cloudflare get deployment cloudflare-tunnel -o json)
just cf-tunnel-verify env=staging
echo "PASS: same-process WAN dependency loss and recovery proven; evidence: $evidence_dir"
