#!/usr/bin/env bash
# Staging-only, process-preserving Cloudflare WAN dependency-loss drill.
set -Eeuo pipefail

readonly EXPECTED_CONTEXT=sugar-staging
readonly EXPECTED_IMAGE='cloudflare/cloudflared:2026.7.3@sha256:e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf'
readonly LABEL_SELECTOR='app.kubernetes.io/name=cloudflare-tunnel,app.kubernetes.io/instance=cloudflare-tunnel'
readonly CONFIRMATION='DISRUPT STAGING CLOUDFLARE WAN FOR THE SAME TWO PROCESSES'
readonly -a ENDPOINTS=(
  https://staging.democratized.space/ https://staging.democratized.space/config.json
  https://staging.democratized.space/healthz https://staging.democratized.space/livez
  https://staging.token.place/ https://staging.token.place/healthz
  https://staging.token.place/livez https://staging.token.place/api/v1/meta
  https://staging.danielsmith.io/ https://staging.danielsmith.io/healthz
  https://staging.danielsmith.io/livez https://staging.jobbot3000.tech/
  https://staging.jobbot3000.tech/healthz https://staging.jobbot3000.tech/livez
  https://staging.jobbot3000.tech/tracker https://staging.jobbot3000.tech/manifest.webmanifest
)

execute=0 env_name= revision= confirmation=
usage() {
  cat <<EOF
Usage: $0 [--execute] --env staging --revision <full-head-sha> [--confirmation '$CONFIRMATION']

Without --execute this performs a read-only plan. Execution additionally requires
SUGARKUBE_WAN_NODE_EXEC to name an already-authorized command accepting NODE COMMAND.
The helper never provisions credentials or weakens SSH host-key checking.
EOF
}
while (($#)); do
  case "$1" in
    --execute) execute=1 ;;
    --env) env_name="${2-}"; shift ;;
    --revision) revision="${2-}"; shift ;;
    --confirmation) confirmation="${2-}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ "$env_name" == staging ]] || die 'the WAN dependency-loss drill is staging-only'
[[ "$(kubectl config current-context)" == "$EXPECTED_CONTEXT" ]] || die "context must be $EXPECTED_CONTEXT"
head="$(git rev-parse HEAD)"
[[ -n "$revision" && "$head" == "$revision" ]] || die "--revision must exactly equal repository HEAD ($head)"
[[ -z "$(git status --porcelain --untracked-files=normal)" ]] || die 'repository worktree must be clean'

helm_json="$(helm -n cloudflare list -o json)"
jq -e '[.[] | select(.name=="cloudflare-tunnel" and .status=="deployed" and .revision=="2" and .chart=="cloudflare-tunnel-0.3.2")] | length==1 and length==1' <<<"$helm_json" >/dev/null || die 'expected exactly cloudflare-tunnel chart 0.3.2 deployed at revision 2'
deployment="$(kubectl -n cloudflare get deployment cloudflare-tunnel -o json)"
jq -e --arg image "$EXPECTED_IMAGE" '
 .metadata.labels["app.kubernetes.io/managed-by"]=="Helm" and
 .metadata.labels["app.kubernetes.io/name"]=="cloudflare-tunnel" and
 .metadata.labels["app.kubernetes.io/instance"]=="cloudflare-tunnel" and
 .spec.replicas==2 and .spec.template.spec.containers[0].image==$image' <<<"$deployment" >/dev/null || die 'Deployment ownership, labels, replicas, or immutable image are not approved'
pods="$(kubectl -n cloudflare get pods -l "$LABEL_SELECTOR" -o json)"
jq -e --arg image "$EXPECTED_IMAGE" '
 [.items[] | select(.metadata.deletionTimestamp==null)] as $p |
 ($p|length)==2 and all($p[];
   .status.phase=="Running" and any(.status.conditions[]?; .type=="Ready" and .status=="True") and
   .metadata.labels["app.kubernetes.io/name"]=="cloudflare-tunnel" and
   .metadata.labels["app.kubernetes.io/instance"]=="cloudflare-tunnel" and
   .status.containerStatuses[0].imageID==$image) and
 ($p|map(.spec.nodeName)|unique|length)==2' <<<"$pods" >/dev/null || die 'expected exactly two Ready approved-image release pods on distinct nodes'

prom_query() {
  local encoded; encoded="$(jq -nr --arg v "$1" '$v|@uri')"
  kubectl get --raw "/api/v1/namespaces/monitoring/services/http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/query?query=$encoded"
}
[[ "$(prom_query 'count(up{namespace="cloudflare",service="cloudflare-tunnel-metrics"} == 1)' | jq -r '.data.result[0].value[1] // "0"')" == 2 ]] || die 'Prometheus targets are unhealthy'
[[ "$(prom_query 'count(cloudflared_tunnel_ha_connections{namespace="cloudflare",service="cloudflare-tunnel-metrics"} >= 4)' | jq -r '.data.result[0].value[1] // "0"')" == 2 ]] || die 'each connector must have at least four HA connections'
[[ "$(prom_query 'count(ALERTS{alertname=~"CloudflareTunnel.*",alertstate="firing"})' | jq -r '.data.result[0].value[1] // "0"')" == 0 ]] || die 'an active Cloudflare alert blocks the drill'
for endpoint in "${ENDPOINTS[@]}"; do
  [[ "$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "$endpoint")" == 200 ]] || die "unhealthy approved endpoint: $endpoint"
done

mapfile -t selected < <(jq -r '.items[] | [.metadata.name,.metadata.uid,.spec.nodeName,.status.containerStatuses[0].restartCount] | @tsv' <<<"$pods" | sort)
owner="sugarkube-cfwan-$(date -u +%Y%m%dT%H%M%SZ)-$$"
printf 'PLAN owner=%s mechanism=pod-netns-nft-output-drop timeout=240s\n' "$owner"
printf 'Selected %s uid=%s node=%s restarts=%s\n' ${selected[0]//$'\t'/ } ${selected[1]//$'\t'/ }
if (( ! execute )); then
  echo 'DRY-RUN: no node command or Kubernetes mutation was performed.'
  exit 0
fi
[[ "$confirmation" == "$CONFIRMATION" ]] || die 'exact typed operator confirmation is required'
node_exec="${SUGARKUBE_WAN_NODE_EXEC-}"
[[ -n "$node_exec" && -x "$node_exec" ]] || die 'safe node execution is not configured; set SUGARKUBE_WAN_NODE_EXEC to an executable NODE COMMAND adapter'

evidence="${SUGARKUBE_WAN_EVIDENCE_DIR:-operator-evidence/$owner}"
mkdir -p "$evidence"; chmod 700 "$evidence"
printf '%s\n' "$pods" | jq '{items:[.items[]|{metadata:{name,uid,labels},spec:{nodeName},status:{phase,conditions,containerStatuses:[.containerStatuses[]|{name,imageID,restartCount,containerID}]}}]}' >"$evidence/pods-before.json"
printf '%s\n' "$deployment" | jq 'del(..|.env? // empty)' >"$evidence/deployment-before.json"
helm -n cloudflare history cloudflare-tunnel -o json >"$evidence/helm-before.json"
secret_metadata() {
  kubectl -n cloudflare get secret tunnel-token \
    -o jsonpath='{.metadata.name}{"\t"}{.metadata.namespace}{"\t"}{.metadata.uid}{"\t"}{.metadata.resourceVersion}{"\t"}{.metadata.creationTimestamp}{"\n"}'
}
secret_metadata >"$evidence/secret-metadata-before.tsv"
prom_query 'up{namespace="cloudflare",service="cloudflare-tunnel-metrics"}' >"$evidence/prometheus-targets-before.json"
prom_query 'cloudflared_tunnel_ha_connections{namespace="cloudflare",service="cloudflare-tunnel-metrics"}' >"$evidence/ha-connections-before.json"
for endpoint in "${ENDPOINTS[@]}"; do printf '%s\t%s\n' "$endpoint" "$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "$endpoint")"; done >"$evidence/endpoints-before.tsv"

declare -a nodes pids sandboxes installed=()
node_run() { "$node_exec" "$1" "$2"; }
remove_rules() {
  local failed=0 i
  for i in "${!installed[@]}"; do
    node_run "${nodes[$i]}" "sudo nsenter -t ${pids[$i]} -n -- nft delete table inet $owner" >/dev/null 2>&1 || failed=1
    node_run "${nodes[$i]}" "sudo nsenter -t ${pids[$i]} -n -- nft list table inet $owner" >/dev/null 2>&1 && failed=1 || true
  done
  if (( failed )); then
    echo 'ERROR: cleanup could not be proven. Run these exact commands:' >&2
    for i in "${!installed[@]}"; do echo "$node_exec ${nodes[$i]} 'sudo nsenter -t ${pids[$i]} -n -- nft delete table inet $owner'" >&2; done
    return 90
  fi
  return 0
}
cleanup_trap() { local rc=$?; trap - EXIT INT TERM; remove_rules || exit 90; exit "$rc"; }
trap cleanup_trap EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for row in "${selected[@]}"; do
  IFS=$'\t' read -r pod uid node restart <<<"$row"; nodes+=("$node")
  identity="$(node_run "$node" "sudo crictl pods --namespace cloudflare --name '^$pod$' -o json")"
  sandbox="$(jq -r --arg uid "$uid" '[.items[]|select(.labels["io.kubernetes.pod.uid"]==$uid)|.id] | if length==1 then .[0] else empty end' <<<"$identity")"
  [[ -n "$sandbox" ]] || die "cannot resolve one exact pod sandbox for $pod"
  pid="$(node_run "$node" "sudo crictl inspectp $sandbox" | jq -r '.info.pid // empty')"
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || die "cannot resolve exact network namespace PID for $pod"
  sandboxes+=("$sandbox"); pids+=("$pid")
  node_run "$node" "sudo nsenter -t $pid -n -- nft list table inet $owner" >/dev/null 2>&1 && die "owner table already exists for $pod" || true
done
for i in "${!nodes[@]}"; do
  printf '%s\t%s\t%s\n' "${nodes[$i]}" "${sandboxes[$i]}" "${pids[$i]}"
done >"$evidence/network-namespaces.tsv"

# Install independently surviving cleanup on every node before disrupting either namespace.
for i in "${!nodes[@]}"; do
  cleanup_cmd="nsenter -t ${pids[$i]} -n -- nft delete table inet $owner"
  node_run "${nodes[$i]}" "sudo systemd-run --quiet --unit ${owner}-cleanup --on-active=240s /usr/bin/$cleanup_cmd" || die "cleanup watchdog installation failed on ${nodes[$i]}"
done
for i in "${!nodes[@]}"; do
  cmd="sudo nsenter -t ${pids[$i]} -n -- sh -ceu 'nft add table inet $owner; nft add chain inet $owner output { type filter hook output priority -300\\; policy accept\\; }; nft add rule inet $owner output counter drop comment \"$owner\"'"
  # Track before the compound command: even a partial nft failure may have created the table.
  installed+=(1)
  node_run "${nodes[$i]}" "$cmd" || die "rule setup failed on ${nodes[$i]}"
done

deadline=$((SECONDS+120)); interrupted=0
while ((SECONDS < deadline)); do
  now="$(kubectl -n cloudflare get pods -l "$LABEL_SELECTOR" -o json)"
  same="$(jq -r --argjson before "$pods" '[.items[]|{uid:.metadata.uid,restart:.status.containerStatuses[0].restartCount,ready:any(.status.conditions[]?;.type=="Ready" and .status=="True")}] as $n | [$before.items[]|{uid:.metadata.uid,restart:.status.containerStatuses[0].restartCount}] as $b | ($n|length)==2 and all($n[] as $x; any($b[]; .uid==$x.uid and .restart==$x.restart)) and all($n[];.ready==false)' <<<"$now")"
  ha="$(prom_query 'sum(cloudflared_tunnel_ha_connections{namespace="cloudflare",service="cloudflare-tunnel-metrics"})' | jq -r '.data.result[0].value[1] // "-1"')"
  [[ "$same" == true ]] || { sleep 5; continue; }
  [[ "$ha" == 0 ]] && { interrupted=1; break; }
  sleep 5
done
(( interrupted )) || die 'interruption was not proven with the same processes, unchanged restarts, NotReady, and zero HA connections'
remove_rules || exit 90
trap - EXIT

deadline=$((SECONDS+300)); recovered=0
while ((SECONDS < deadline)); do
  now="$(kubectl -n cloudflare get pods -l "$LABEL_SELECTOR" -o json)"
  same_ready="$(jq -r --argjson before "$pods" '[.items[]|{uid:.metadata.uid,restart:.status.containerStatuses[0].restartCount,ready:any(.status.conditions[]?;.type=="Ready" and .status=="True")}] as $n | [$before.items[]|{uid:.metadata.uid,restart:.status.containerStatuses[0].restartCount}] as $b | ($n|length)==2 and all($n[] as $x; $x.ready and any($b[]; .uid==$x.uid and .restart==$x.restart))' <<<"$now")"
  ha="$(prom_query 'count(cloudflared_tunnel_ha_connections{namespace="cloudflare",service="cloudflare-tunnel-metrics"} >= 4)' | jq -r '.data.result[0].value[1] // "0"')"
  [[ "$same_ready" == true && "$ha" == 2 ]] && { recovered=1; break; }
  sleep 5
done
(( recovered )) || die 'same-process recovery with four HA connections each was not proven in five minutes'
for endpoint in "${ENDPOINTS[@]}"; do [[ "$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "$endpoint")" == 200 ]] || die "endpoint did not recover: $endpoint"; done
diff -u "$evidence/helm-before.json" <(helm -n cloudflare history cloudflare-tunnel -o json) >/dev/null || die 'Helm history changed'
diff -u "$evidence/secret-metadata-before.tsv" <(secret_metadata) >/dev/null || die 'Secret metadata changed'
diff -u "$evidence/deployment-before.json" <(kubectl -n cloudflare get deployment cloudflare-tunnel -o json | jq 'del(..|.env? // empty)') >/dev/null || die 'Deployment changed'
just cf-tunnel-verify env=staging
echo "PASS: $owner interrupted and recovered the same two cloudflared processes; evidence=$evidence"
