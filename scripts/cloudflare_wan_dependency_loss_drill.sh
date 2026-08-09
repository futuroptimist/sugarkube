#!/usr/bin/env bash
# Staging-only, process-preserving Cloudflare WAN dependency-loss drill.
set -Eeuo pipefail

readonly EXPECTED_CONTEXT=sugar-staging
readonly EXPECTED_IMAGE='cloudflare/cloudflared:2026.7.3@sha256:e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf'
readonly EXPECTED_CONFIRMATION='INTERRUPT BOTH STAGING CLOUDFLARE CONNECTORS'
readonly SELECTOR='app.kubernetes.io/name=cloudflare-tunnel,app.kubernetes.io/instance=cloudflare-tunnel'
readonly MAX_DISRUPTION_SECONDS=240
execute=0
env_name=staging
confirmation=''
evidence_dir=''

usage() {
  cat <<'EOF'
Usage: cloudflare_wan_dependency_loss_drill.sh [--execute] [--env staging]
       [--confirm 'INTERRUPT BOTH STAGING CLOUDFLARE CONNECTORS'] [--evidence-dir DIR]

The default is a non-mutating plan. Execution also requires CF_WAN_APPROVED_REVISION
and CF_WAN_NODE_EXEC, an executable invoked as: NODE_EXEC <node> <shell-command>.
EOF
}
while (($#)); do
  case "$1" in
    --execute) execute=1 ;;
    --env) env_name="${2:?missing --env value}"; shift ;;
    --confirm) confirmation="${2:?missing --confirm value}"; shift ;;
    --evidence-dir) evidence_dir="${2:?missing --evidence-dir value}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

die() { echo "ERROR: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null || die "required command not found: $1"; }
for command in git kubectl helm jq curl; do need "${command}"; done
[[ "${env_name}" == staging ]] || die 'WAN dependency-loss drill is staging-only.'
[[ "$(kubectl config current-context)" == "${EXPECTED_CONTEXT}" ]] || die "expected context ${EXPECTED_CONTEXT}."

repo_root="$(git rev-parse --show-toplevel)"
head="$(git -C "${repo_root}" rev-parse HEAD)"
[[ -z "$(git -C "${repo_root}" status --porcelain --untracked-files=normal)" ]] || die 'repository tree is dirty.'
if ((execute)); then
  [[ -n "${CF_WAN_APPROVED_REVISION:-}" && "${head}" == "${CF_WAN_APPROVED_REVISION}" ]] || die 'HEAD is not the explicitly approved revision.'
fi

releases="$(helm -n cloudflare list -o json)"
jq -e '[.[] | select(.name=="cloudflare-tunnel" and .status=="deployed")] | length == 1' <<<"${releases}" >/dev/null || die 'expected exactly one deployed cloudflare-tunnel release.'
revision="$(jq -r '.[] | select(.name=="cloudflare-tunnel") | .revision' <<<"${releases}")"
[[ "${revision}" == 2 ]] || die "cloudflare-tunnel must be Helm revision 2; got ${revision}."

deployment="$(kubectl -n cloudflare get deployment cloudflare-tunnel -o json)"
jq -e --arg image "${EXPECTED_IMAGE}" '
 .metadata.labels["app.kubernetes.io/managed-by"] == "Helm" and
 .metadata.labels["app.kubernetes.io/name"] == "cloudflare-tunnel" and
 .metadata.labels["app.kubernetes.io/instance"] == "cloudflare-tunnel" and
 .spec.template.spec.containers[0].image == $image' <<<"${deployment}" >/dev/null || die 'Deployment ownership, labels, or immutable image differ.'

pods="$(kubectl -n cloudflare get pods -l "${SELECTOR}" -o json)"
jq -e --arg image "${EXPECTED_IMAGE}" '
 [.items[] | select(.metadata.deletionTimestamp == null)] as $p |
 ($p|length)==2 and all($p[];
   .metadata.labels["app.kubernetes.io/name"]=="cloudflare-tunnel" and
   .metadata.labels["app.kubernetes.io/instance"]=="cloudflare-tunnel" and
   .status.phase=="Running" and any(.status.conditions[]?; .type=="Ready" and .status=="True") and
   .spec.containers[0].image==$image) and ($p|map(.spec.nodeName)|unique|length)==2
' <<<"${pods}" >/dev/null || die 'expected exactly two Ready, correctly labelled connectors on distinct nodes with the approved image.'

prom_query() {
  local encoded
  encoded="$(jq -nr --arg v "$1" '$v|@uri')"
  kubectl get --raw "/api/v1/namespaces/monitoring/services/http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/query?query=${encoded}"
}
[[ "$(prom_query 'count(up{namespace="cloudflare",service="cloudflare-tunnel-metrics"} == 1)' | jq -r '.data.result[0].value[1] // "0"')" == 2 ]] || die 'Prometheus connector targets are unhealthy.'
[[ "$(prom_query 'count(cloudflared_tunnel_ha_connections{namespace="cloudflare",service="cloudflare-tunnel-metrics"} >= 4)' | jq -r '.data.result[0].value[1] // "0"')" == 2 ]] || die 'each connector must have at least four HA connections.'
[[ "$(prom_query 'count(ALERTS{alertname=~"CloudflareTunnel(NoHealthyConnections|ConnectionsDegraded|MetricsTargetsDown)",alertstate="firing"})' | jq -r '.data.result[0].value[1] // "0"')" == 0 ]] || die 'a Cloudflare alert is active.'

need yq
mapfile -t endpoints < <(yq -r '.spec.targets.staticConfig.static[]? // empty' "${repo_root}/clusters/staging/observability/probes/public-apps.yaml")
((${#endpoints[@]} == 16)) || die 'approved staging endpoint inventory must contain exactly 16 entries.'
check_endpoints() {
  local endpoint code
  for endpoint in "${endpoints[@]}"; do
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "${endpoint}")" || return 1
    [[ "${code}" == 200 ]] || return 1
  done
}
check_endpoints || die 'one or more approved public staging endpoints are unhealthy.'

cat <<EOF
PLAN (no mutation unless --execute was supplied)
  mechanism: pod-network-namespace-local nftables edge-port output drop table
  pods: $(jq -r '[.items[].metadata.name]|join(", ")' <<<"${pods}")
  nodes: $(jq -r '[.items[].spec.nodeName]|join(", ")' <<<"${pods}")
  maximum disruption: ${MAX_DISRUPTION_SECONDS}s
  cleanup: per-node transient systemd watchdog plus exact table deletion
EOF
((execute)) || exit 0
[[ "${confirmation}" == "${EXPECTED_CONFIRMATION}" ]] || die "confirmation must exactly equal: ${EXPECTED_CONFIRMATION}"
[[ -n "${CF_WAN_NODE_EXEC:-}" && -x "${CF_WAN_NODE_EXEC}" ]] || die 'safe node execution is unavailable; set CF_WAN_NODE_EXEC to an executable authenticated node runner.'

owner="cfwan_$(date -u +%Y%m%dT%H%M%SZ)_$$_${RANDOM}"
owner="${owner//-/_}"
[[ "${owner}" =~ ^[a-zA-Z0-9_]+$ ]] || die 'invalid generated owner.'
evidence_dir="${evidence_dir:-${HOME}/operator-evidence/cloudflare-wan-dependency-loss-drill-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -m 700 -p "${evidence_dir}"
printf '%s\n' "owner=${owner}" "revision=${head}" >"${evidence_dir}/summary.txt"
jq '[.items[] | {name:.metadata.name,uid:.metadata.uid,node:.spec.nodeName,image:.spec.containers[0].image,restarts:([.status.containerStatuses[].restartCount]|add),sandboxID:(.status.containerStatuses[0].containerID // "")} ]' <<<"${pods}" >"${evidence_dir}/pods-before.json"
helm -n cloudflare history cloudflare-tunnel -o json >"${evidence_dir}/helm-before.json"
kubectl -n cloudflare get secret tunnel-token -o json | jq '{apiVersion,kind,metadata:{name:.metadata.name,namespace:.metadata.namespace,uid:.metadata.uid,resourceVersion:.metadata.resourceVersion,creationTimestamp:.metadata.creationTimestamp}}' >"${evidence_dir}/secret-metadata-before.json"
printf '%s\n' "${deployment}" >"${evidence_dir}/deployment-before.json"
prom_query 'cloudflared_tunnel_ha_connections{namespace="cloudflare",service="cloudflare-tunnel-metrics"}' >"${evidence_dir}/metrics-before.json"
for endpoint in "${endpoints[@]}"; do
  printf '%s\t%s\n' "${endpoint}" "$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "${endpoint}")"
done >"${evidence_dir}/endpoints-before.tsv"

node_exec() { "${CF_WAN_NODE_EXEC}" "$1" "$2"; }
declare -a installed_nodes=() cleanup_commands=()
cleanup_ok=1
cleanup() {
  trap - EXIT INT TERM
  local i
  for ((i=${#installed_nodes[@]}-1; i>=0; i--)); do
    if ! node_exec "${installed_nodes[i]}" "${cleanup_commands[i]}"; then cleanup_ok=0; fi
  done
  if ((cleanup_ok==0)); then
    echo 'ERROR: automated cleanup could not be proven. Run these exact commands through the approved node runner:' >&2
    for ((i=0; i<${#installed_nodes[@]}; i++)); do printf '  node=%q command=%q\n' "${installed_nodes[i]}" "${cleanup_commands[i]}" >&2; done
    exit 1
  fi
}
trap cleanup EXIT INT TERM

mapfile -t pod_rows < <(jq -r '.items[] | [.metadata.name,.metadata.uid,.spec.nodeName,([.status.containerStatuses[].restartCount]|add)] | @tsv' <<<"${pods}")
for row in "${pod_rows[@]}"; do
  IFS=$'\t' read -r pod uid node restarts <<<"${row}"
  resolve="sid=\$(sudo crictl pods --namespace cloudflare --name '^${pod}$' -q); test \"\$(printf '%s\\n' \$sid | sed '/^$/d' | wc -l)\" -eq 1; sudo crictl inspectp \$sid | jq -er '.info.pid'"
  pid="$(node_exec "${node}" "${resolve}")" || die "cannot resolve exact sandbox network namespace for ${pod}."
  [[ "${pid}" =~ ^[0-9]+$ ]] || die "ambiguous sandbox PID for ${pod}."
  printf '%s\t%s\t%s\t%s\n' "${pod}" "${uid}" "${node}" "${pid}" >>"${evidence_dir}/network-namespaces.tsv"
  table="${owner}_${pid}"
  cleanup_cmd="sudo nsenter -t ${pid} -n nft delete table inet ${table}"
  node_exec "${node}" "! sudo nsenter -t ${pid} -n nft list table inet ${table} >/dev/null 2>&1" || die "owner-tagged rule already exists for ${pod}."
  # The watchdog is installed and verified before any packet is dropped.
  watchdog="sudo systemd-run --unit=${table}_cleanup --collect --on-active=${MAX_DISRUPTION_SECONDS}s /usr/sbin/nsenter -t ${pid} -n /usr/sbin/nft delete table inet ${table}"
  node_exec "${node}" "${watchdog} && sudo systemctl is-active --quiet ${table}_cleanup.timer"
  installed_nodes+=("${node}"); cleanup_commands+=("${cleanup_cmd}")
done

# Only after every watchdog exists do we disrupt the two exact namespaces.
for row in "${pod_rows[@]}"; do
  IFS=$'\t' read -r pod uid node restarts <<<"${row}"
  pid="$(node_exec "${node}" "sid=\$(sudo crictl pods --namespace cloudflare --name '^${pod}$' -q); sudo crictl inspectp \$sid | jq -er '.info.pid'")"
  table="${owner}_${pid}"
  node_exec "${node}" "sudo nsenter -t ${pid} -n nft add table inet ${table}; sudo nsenter -t ${pid} -n nft 'add chain inet ${table} output { type filter hook output priority -200; policy accept; }'; sudo nsenter -t ${pid} -n nft 'add rule inet ${table} output meta l4proto { tcp, udp } th dport { 443, 7844 } counter drop'; sudo nsenter -t ${pid} -n nft list table inet ${table}"
done

deadline=$((SECONDS+120)); interrupted=0
while ((SECONDS<deadline)); do
  now="$(kubectl -n cloudflare get pods -l "${SELECTOR}" -o json)"
  same="$(jq --argjson before "${pods}" '[.items[]|{uid:.metadata.uid,restarts:([.status.containerStatuses[].restartCount]|add)}] == [$before.items[]|{uid:.metadata.uid,restarts:([.status.containerStatuses[].restartCount]|add)}]' <<<"${now}")"
  [[ "${same}" == true ]] || die 'a connector UID or restart count changed during interruption.'
  ready="$(jq '[.items[]|select(any(.status.conditions[]?;.type=="Ready" and .status=="True"))]|length' <<<"${now}")"
  ha="$(prom_query 'count(cloudflared_tunnel_ha_connections{namespace="cloudflare",service="cloudflare-tunnel-metrics"} == 0)' | jq -r '.data.result[0].value[1] // "0"')"
  if [[ "${ready}" == 0 && "${ha}" == 2 ]]; then interrupted=1; break; fi
  sleep 5
done
((interrupted)) || die 'did not prove both original processes NotReady with zero HA connections.'
cleanup

deadline=$((SECONDS+300)); recovered=0
while ((SECONDS<deadline)); do
  now="$(kubectl -n cloudflare get pods -l "${SELECTOR}" -o json)"
  same="$(jq --argjson before "${pods}" '[.items[]|{uid:.metadata.uid,restarts:([.status.containerStatuses[].restartCount]|add)}] == [$before.items[]|{uid:.metadata.uid,restarts:([.status.containerStatuses[].restartCount]|add)}]' <<<"${now}")"
  [[ "${same}" == true ]] || die 'a connector was replaced or restarted during recovery.'
  ready="$(jq '[.items[]|select(any(.status.conditions[]?;.type=="Ready" and .status=="True"))]|length' <<<"${now}")"
  ha="$(prom_query 'count(cloudflared_tunnel_ha_connections{namespace="cloudflare",service="cloudflare-tunnel-metrics"} >= 4)' | jq -r '.data.result[0].value[1] // "0"')"
  if [[ "${ready}" == 2 && "${ha}" == 2 ]]; then recovered=1; break; fi
  sleep 5
done
((recovered)) || die 'same-pod recovery with four HA connections each was not proven within five minutes.'
check_endpoints || die 'approved endpoints did not recover to HTTP 200.'
cmp -s <(helm -n cloudflare history cloudflare-tunnel -o json) "${evidence_dir}/helm-before.json" || die 'Helm history changed.'
cmp -s <(kubectl -n cloudflare get secret tunnel-token -o json | jq '{apiVersion,kind,metadata:{name:.metadata.name,namespace:.metadata.namespace,uid:.metadata.uid,resourceVersion:.metadata.resourceVersion,creationTimestamp:.metadata.creationTimestamp}}') "${evidence_dir}/secret-metadata-before.json" || die 'Secret metadata changed.'
cmp -s <(kubectl -n cloudflare get deployment cloudflare-tunnel -o json) "${evidence_dir}/deployment-before.json" || die 'Deployment changed.'
just cf-tunnel-verify env=staging
printf 'Drill passed; sanitized evidence: %s\n' "${evidence_dir}"
