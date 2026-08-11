#!/usr/bin/env bash
# Staging-only, process-preserving Cloudflare WAN dependency-loss drill.
set -Eeuo pipefail

readonly EXPECTED_CONTEXT=sugar-staging
readonly EXPECTED_IMAGE='cloudflare/cloudflared:2026.7.3@sha256:e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf'
readonly EXPECTED_CHART='cloudflare-tunnel-0.3.2'
readonly EXPECTED_HELM_REVISION=2
readonly CONFIRMATION='DISRUPT STAGING CLOUDFLARE WAN FOR SAME-PROCESS RECOVERY'
readonly SELECTOR='app.kubernetes.io/name=cloudflare-tunnel,app.kubernetes.io/instance=cloudflare-tunnel'
readonly CRICTL='/usr/local/bin/crictl'
readonly CURL='/usr/bin/curl'
readonly DISRUPTION_SECONDS=180
readonly RECOVERY_SECONDS=300

execute=0
manual_node_plan=0
env_name=staging
confirmation=''
owner=''
evidence_dir=''
declare -a attempted_indices=()
declare -a pod_names=() pod_uids=() pod_nodes=() pod_restarts=() pod_sandboxes=() pod_pids=() pod_netns=()
cleanup_failed=0
declare -a preflight_http=()

usage() {
  cat <<'EOF'
Usage: cloudflare_wan_dependency_loss_drill.sh [--execute] [--env staging]
       cloudflare_wan_dependency_loss_drill.sh --manual-node-plan [--env staging]
       [--confirm 'DISRUPT STAGING CLOUDFLARE WAN FOR SAME-PROCESS RECOVERY']

The default offline plan requires no approval coordinates or cluster/node tools.
Both --manual-node-plan and --execute require:
  CF_DRILL_APPROVED_REVISION=<full git revision>
  CF_DRILL_EXPECTED_OBSERVABILITY_REVISION=<separately reviewed positive integer>
Execution additionally requires the exact confirmation and:
  CF_DRILL_NODE_EXECUTOR=<executable accepting NODE and COMMAND arguments>
The executor is deliberately not SSH: authentication and sudo must be established separately.
It must execute the supplied command verbatim on the named node and must not log credentials.
EOF
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
node_exec() { "${CF_DRILL_NODE_EXECUTOR}" "$1" "$2"; }
table_for() {
  local digest
  digest="$(printf '%s' "${owner}" | sha256sum | cut -d' ' -f1)"
  printf 'cfwd_%s' "${digest:0:20}"
}

render_manual_node_plan() {
  local i table unit resolve guard watchdog_body watchdog disruption cleanup
  local -a disruptions=() cleanups=()
  table="$(table_for)"
  printf 'MANUAL NODE PLAN -- commands were rendered but NOT EXECUTED.\n'
  printf 'Observability Helm revision: expected=%s observed=%s\n' "${expected_observability_revision}" "${observed_observability_revision}"
  printf 'Run each record through a separately authenticated, host-key-verified session for its exact node.\n'
  printf 'Complete and verify both watchdog commands successfully before running either DISRUPTION command.\n'
  printf 'After the observation window, run both CLEANUP commands.\n'
  printf 'If either DISRUPTION command fails or you abort after any disruption, immediately run both CLEANUP commands.\n'
  for i in 0 1; do
    unit="${owner}-cleanup.service"
    resolve="sandboxes=\"\$(sudo ${CRICTL} pods --name '^${pod_names[$i]}$' -q)\" && set -- \${sandboxes} && test \"\$#\" -eq 1 && sandbox=\"\$1\" && inspect=\"\$(sudo ${CRICTL} inspectp \"\${sandbox}\")\" && test \"\$(printf '%s\\n' \"\${inspect}\" | /usr/bin/jq -r '.status.labels[\"io.kubernetes.pod.uid\"]')\" = '${pod_uids[$i]}' && pid=\"\$(printf '%s\\n' \"\${inspect}\" | /usr/bin/jq -r '.info.pid')\" && case \"\${pid}\" in ''|0|*[!0-9]*) exit 64;; esac && netns=\"\$(sudo /usr/bin/readlink /proc/\${pid}/ns/net)\" && case \"\${netns}\" in 'net:['*']') :;; *) exit 65;; esac"
    watchdog_body="/bin/sh -c 'test \"\$(/usr/bin/readlink /proc/self/ns/net)\" = \"\$1\" || exit 70; /bin/sleep 240; /usr/sbin/nft delete table inet ${table} 2>/dev/null || true; ruleset=\"\$(/usr/sbin/nft -j list ruleset)\" || exit 71; printf \"%s\\n\" \"\${ruleset}\" | /usr/bin/jq -e --arg table ${table} '\"'\"'[.nftables[]?.table? | select(.family==\"inet\" and .name==\$table)] | length == 0'\"'\"' >/dev/null' sh \"\${netns}\""
    watchdog="${resolve} && sudo /usr/bin/systemd-run --unit '${unit%.service}' --collect /usr/bin/nsenter -t \"\${pid}\" -n ${watchdog_body} && sudo /usr/bin/systemctl is-active --quiet '${unit}' && watchdog_pid=\"\$(sudo /usr/bin/systemctl show --property MainPID --value '${unit}')\" && case \"\${watchdog_pid}\" in ''|0|*[!0-9]*) exit 66;; esac && test \"\$(sudo /usr/bin/readlink /proc/\${watchdog_pid}/ns/net)\" = \"\${netns}\""
    printf 'WATCHDOG node=%q pod=%q uid=%q owner=%q table=%q command=%q\n' "${pod_nodes[$i]}" "${pod_names[$i]}" "${pod_uids[$i]}" "${owner}" "${table}" "${watchdog}"
  done
  for i in 0 1; do
    unit="${owner}-cleanup.service"
    resolve="sandboxes=\"\$(sudo ${CRICTL} pods --name '^${pod_names[$i]}$' -q)\" && set -- \${sandboxes} && test \"\$#\" -eq 1 && sandbox=\"\$1\" && inspect=\"\$(sudo ${CRICTL} inspectp \"\${sandbox}\")\" && test \"\$(printf '%s\\n' \"\${inspect}\" | /usr/bin/jq -r '.status.labels[\"io.kubernetes.pod.uid\"]')\" = '${pod_uids[$i]}' && pid=\"\$(printf '%s\\n' \"\${inspect}\" | /usr/bin/jq -r '.info.pid')\" && case \"\${pid}\" in ''|0|*[!0-9]*) exit 64;; esac && netns=\"\$(sudo /usr/bin/readlink /proc/\${pid}/ns/net)\" && case \"\${netns}\" in 'net:['*']') :;; *) exit 65;; esac"
    guard="sudo /usr/bin/systemctl is-active --quiet '${unit}' && watchdog_pid=\"\$(sudo /usr/bin/systemctl show --property MainPID --value '${unit}')\" && case \"\${watchdog_pid}\" in ''|0|*[!0-9]*) exit 66;; esac && test \"\$(sudo /usr/bin/readlink /proc/\${watchdog_pid}/ns/net)\" = \"\${netns}\""
    disruption="${resolve} && ${guard} && ruleset=\"\$(sudo /usr/bin/nsenter -t \"\${pid}\" -n /usr/sbin/nft -j list ruleset)\" && printf '%s\\n' \"\${ruleset}\" | /usr/bin/jq -e --arg table '${table}' '[.nftables[]?.table? | select(.family==\"inet\" and .name==\$table)] | length == 0' >/dev/null && sudo /usr/bin/nsenter -t \"\${pid}\" -n /usr/sbin/nft 'add table inet ${table}; add chain inet ${table} output { type filter hook output priority -10; policy accept; }; add rule inet ${table} output udp dport { 7844, 443 } counter drop comment \"${owner}\"; add rule inet ${table} output tcp dport { 7844, 443 } counter drop comment \"${owner}\"'"
    cleanup="${resolve} && { sudo /usr/bin/nsenter -t \"\${pid}\" -n /usr/sbin/nft delete table inet ${table} 2>/dev/null || true; } && ruleset=\"\$(sudo /usr/bin/nsenter -t \"\${pid}\" -n /usr/sbin/nft -j list ruleset)\" && printf '%s\\n' \"\${ruleset}\" | /usr/bin/jq -e --arg table '${table}' '[.nftables[]?.table? | select(.family==\"inet\" and .name==\$table)] | length == 0' >/dev/null"
    disruptions[i]="${disruption}"
    cleanups[i]="${cleanup}"
  done
  for i in 0 1; do
    printf 'DISRUPTION node=%q pod=%q uid=%q owner=%q table=%q command=%q\n' "${pod_nodes[$i]}" "${pod_names[$i]}" "${pod_uids[$i]}" "${owner}" "${table}" "${disruptions[$i]}"
  done
  for i in 0 1; do
    printf 'CLEANUP node=%q pod=%q uid=%q owner=%q table=%q command=%q\n' "${pod_nodes[$i]}" "${pod_names[$i]}" "${pod_uids[$i]}" "${owner}" "${table}" "${cleanups[$i]}"
  done
  printf 'BLOCKED: manual-node plan only; the drill was not executed and has not passed.\n'
}

validate_observability_history() {
  local history="$1" phase="$2" deployed_count revision revision_json
  deployed_count="$(jq '[.[] | select(.status == "deployed")] | length' <<<"${history}")" || \
    die "${phase} observability Helm history is not valid JSON"
  [[ "${deployed_count}" == 1 ]] || \
    die "${phase} observability Helm history must contain exactly one deployed entry (expected revision ${expected_observability_revision}; observed deployed entries ${deployed_count})"
  revision_json="$(jq -c '[.[] | select(.status == "deployed")][0].revision' <<<"${history}")"
  jq -e 'type == "number" and . > 0 and floor == .' <<<"${revision_json}" >/dev/null || \
    die "${phase} observability deployed revision is not a positive integer-valued JSON number (expected ${expected_observability_revision}; observed ${revision_json})"
  revision="$(jq -r '.' <<<"${revision_json}")"
  [[ "${revision}" == "${expected_observability_revision}" ]] || \
    die "${phase} observability Helm revision mismatch (expected ${expected_observability_revision}; observed ${revision})"
  observed_observability_revision="${revision}"
}

manual_cleanup() {
  local i table; table="$(table_for)"
  printf 'MANUAL CLEANUP REQUIRED (run through an authenticated, host-key-verified node session):\n' >&2
  for i in "${!pod_nodes[@]}"; do
    printf '  node=%q command=%q\n' "${pod_nodes[$i]}" \
      "test \"\$(sudo ${CRICTL} inspectp ${pod_sandboxes[$i]:-SANDBOX_ID} | /usr/bin/jq -r '.status.labels[\"io.kubernetes.pod.uid\"]')\" = '${pod_uids[$i]:-POD_UID}' && test \"\$(sudo /usr/bin/readlink /proc/${pod_pids[$i]:-POD_SANDBOX_PID}/ns/net)\" = '${pod_netns[$i]:-NETNS_INODE}' && { sudo /usr/bin/nsenter -t ${pod_pids[$i]:-POD_SANDBOX_PID} -n /usr/sbin/nft delete table inet ${table} 2>/dev/null || true; } && ruleset=\"\$(sudo /usr/bin/nsenter -t ${pod_pids[$i]:-POD_SANDBOX_PID} -n /usr/sbin/nft -j list ruleset)\" && printf '%s\\n' \"\${ruleset}\" | /usr/bin/jq -e --arg table '${table}' '[.nftables[]?.table? | select(.family==\"inet\" and .name==\$table)] | length == 0' >/dev/null" >&2
  done
}

cleanup() {
  local status="${1:-$?}" node i position command table
  trap - EXIT INT TERM
  cleanup_failed=0
  table="$(table_for)"
  for ((position=${#attempted_indices[@]}-1; position>=0; position--)); do
    i="${attempted_indices[$position]}"
    node="${pod_nodes[$i]}"
    command="test \"\$(sudo ${CRICTL} inspectp ${pod_sandboxes[$i]} | /usr/bin/jq -r '.status.labels[\"io.kubernetes.pod.uid\"]')\" = '${pod_uids[$i]}' && test \"\$(sudo /usr/bin/readlink /proc/${pod_pids[$i]}/ns/net)\" = '${pod_netns[$i]}' && { sudo /usr/bin/nsenter -t ${pod_pids[$i]} -n /usr/sbin/nft delete table inet ${table} 2>/dev/null || true; } && ruleset=\"\$(sudo /usr/bin/nsenter -t ${pod_pids[$i]} -n /usr/sbin/nft -j list ruleset)\" && printf '%s\\n' \"\${ruleset}\" | /usr/bin/jq -e --arg table '${table}' '[.nftables[]?.table? | select(.family==\"inet\" and .name==\$table)] | length == 0' >/dev/null"
    if node_exec "${node}" "${command}" >/dev/null; then
      unset 'attempted_indices[position]'
    else
      cleanup_failed=1
    fi
  done
  if ((cleanup_failed)); then manual_cleanup; status=1; fi
  exit "${status}"
}

for arg in "$@"; do
  case "${arg}" in
    --execute) execute=1 ;;
    --manual-node-plan) manual_node_plan=1 ;;
    --env=*) env_name="${arg#*=}" ;;
    env=*) env_name="${arg#*=}" ;;
    --confirm=*) confirmation="${arg#*=}" ;;
    --evidence-dir=*) evidence_dir="${arg#*=}" ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: ${arg}" ;;
  esac
done

[[ "${env_name}" == staging ]] || die 'the WAN drill is staging-only'
if ((!execute && !manual_node_plan)); then
  cat <<EOF
PLAN ONLY -- no cluster or node command was run.
Mechanism: create one uniquely named nftables inet/output table inside each of the two selected
pod network namespaces. Its owner-commented edge-port rules affect new and established QUIC/TCP traffic
while cloudflared remains alive. Before either rule, install a 240-second transient systemd cleanup
watchdog on that node. Delete only that exact table during normal cleanup.
Execution remains blocked until every read-only preflight and the typed confirmation passes.
Owner format: cfwandrill-<UTC timestamp>-<operator PID>
EOF
  exit 0
fi

owner="cfwandrill-$(date -u +%Y%m%dT%H%M%SZ)-$$"
if ((execute)); then
  [[ "${confirmation}" == "${CONFIRMATION}" ]] || die "confirmation must exactly equal: ${CONFIRMATION}"
fi
expected_observability_revision="${CF_DRILL_EXPECTED_OBSERVABILITY_REVISION:-}"
[[ "${expected_observability_revision}" =~ ^[1-9][0-9]*$ ]] || \
  die 'CF_DRILL_EXPECTED_OBSERVABILITY_REVISION is required and must be a canonical positive decimal integer (for example, 10; no signs, whitespace, or leading zeros)'
[[ -n "${CF_DRILL_APPROVED_REVISION:-}" ]] || die 'CF_DRILL_APPROVED_REVISION is required'
[[ "$(kubectl config current-context)" == "${EXPECTED_CONTEXT}" ]] || die "context must be ${EXPECTED_CONTEXT}"
[[ -z "$(git status --porcelain)" ]] || die 'repository worktree must be clean'
head_revision="$(git rev-parse HEAD)"
[[ "${head_revision}" == "${CF_DRILL_APPROVED_REVISION}" ]] || die 'repository revision is not approved'

releases="$(helm -n cloudflare list -o json)"
[[ "$(jq '[.[]|select(.name=="cloudflare-tunnel" and .status=="deployed")]|length' <<<"${releases}")" == 1 ]] || \
  die 'expected exactly one deployed cloudflare-tunnel release'
[[ "$(jq -r '.[]|select(.name=="cloudflare-tunnel")|.chart' <<<"${releases}")" == "${EXPECTED_CHART}" ]] || die 'wrong Cloudflare chart'
cf_history="$(helm -n cloudflare history cloudflare-tunnel -o json)"
[[ "$(jq -r '[.[]|select(.status=="deployed")][0].revision' <<<"${cf_history}")" == "${EXPECTED_HELM_REVISION}" ]] || die 'Cloudflare Helm revision must be 2'
obs_history="$(helm -n monitoring history kube-prometheus-stack -o json)"
observed_observability_revision=''
validate_observability_history "${obs_history}" 'preflight'

deployment="$(kubectl -n cloudflare get deployment cloudflare-tunnel -o json)"
jq -e --arg image "${EXPECTED_IMAGE}" '
 .metadata.labels["app.kubernetes.io/managed-by"]=="Helm" and
 .metadata.labels["app.kubernetes.io/name"]=="cloudflare-tunnel" and
 .metadata.labels["app.kubernetes.io/instance"]=="cloudflare-tunnel" and
 .spec.replicas==2 and .spec.template.spec.containers[0].image==$image
 and (.spec.template.spec.containers[0] | has("livenessProbe") | not)
 and .spec.template.spec.containers[0].readinessProbe.httpGet.path=="/ready"
 and .spec.template.spec.containers[0].readinessProbe.httpGet.port==2000
' <<<"${deployment}" >/dev/null || die 'Deployment ownership, replicas, immutable image is not approved, or probe lifecycle is unsafe'
deployment_fingerprint="$(jq -S '{metadata:{labels:.metadata.labels,annotations:.metadata.annotations,uid:.metadata.uid,generation:.metadata.generation},spec:.spec}' <<<"${deployment}" | sha256sum | cut -d' ' -f1)"
deployment_generation="$(jq -r '.metadata.generation' <<<"${deployment}")"

# Reuse the repository verifier's complete strategy/topology/probe contract before mutation.
just cf-tunnel-verify env=staging

pods="$(kubectl -n cloudflare get pods -l "${SELECTOR}" -o json)"
mapfile -t records < <(jq -r --arg image "${EXPECTED_IMAGE}" '
 [.items[]|select(.metadata.deletionTimestamp==null)] as $all |
 if ($all|length)!=2 then empty else $all[]|select(.status.phase=="Running" and
   any(.status.conditions[]?;.type=="Ready" and .status=="True") and
   .metadata.labels["app.kubernetes.io/name"]=="cloudflare-tunnel" and
   .metadata.labels["app.kubernetes.io/instance"]=="cloudflare-tunnel" and
   .spec.containers[0].image==$image) end |
 [.metadata.name,.metadata.uid,.spec.nodeName,([.status.containerStatuses[].restartCount]|add)]|@tsv
' <<<"${pods}")
[[ "${#records[@]}" == 2 ]] || die 'exactly two Ready, exactly labelled connector pods are required'
for record in "${records[@]}"; do
  IFS=$'\t' read -r name uid node restarts <<<"${record}"
  pod_names+=("${name}"); pod_uids+=("${uid}"); pod_nodes+=("${node}"); pod_restarts+=("${restarts}")
done
[[ "${pod_nodes[0]}" != "${pod_nodes[1]}" ]] || die 'connector pods must be on distinct nodes'

prom_query() { local encoded; encoded="$(jq -nr --arg q "$1" '$q|@uri')"; kubectl get --raw "/api/v1/namespaces/monitoring/services/http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/query?query=${encoded}"; }
[[ "$(prom_query 'count(up{namespace="cloudflare",service="cloudflare-tunnel-metrics"} == 1)' | jq -r '.data.result[0].value[1]//"0"')" == 2 ]] || die 'Prometheus targets are unhealthy'
[[ "$(prom_query 'count(cloudflared_tunnel_ha_connections{namespace="cloudflare",service="cloudflare-tunnel-metrics"} >= 4)' | jq -r '.data.result[0].value[1]//"0"')" == 2 ]] || die 'each connector must have at least four HA connections'
[[ "$(prom_query 'count(ALERTS{alertname=~"CloudflareTunnel.*",alertstate="firing"})' | jq -r '.data.result[0].value[1]//"0"')" == 0 ]] || die 'a Cloudflare alert is active'

mapfile -t endpoints < <(ruby -ryaml -e 'YAML.load_stream(File.read(ARGV[0])){|d| next unless d.is_a?(Hash); t=d.dig("spec","targets","staticConfig","static") || []; t.each{|x| puts x}}' clusters/staging/observability/probes/public-apps.yaml | sort -u)
[[ "${#endpoints[@]}" == 16 ]] || die 'approved staging endpoint manifest must contain exactly 16 URLs'
http_command="${CF_DRILL_HTTP_COMMAND:-curl}"
for endpoint in "${endpoints[@]}"; do
  code="$(${http_command} -fsS -o /dev/null -w '%{http_code}' --max-time 15 "${endpoint}")"
  preflight_http+=("${endpoint}"$'\t'"${code}")
  [[ "${code}" == 200 ]] || die "unhealthy endpoint: ${endpoint}"
done

# Metadata only: never request Secret JSON/YAML or its data.
secret_metadata="$(kubectl -n cloudflare get secret tunnel-token -o jsonpath='{.metadata.uid}{"\t"}{.metadata.resourceVersion}{"\t"}{.metadata.creationTimestamp}{"\n"}')"
[[ -n "${secret_metadata}" ]] || die 'tunnel-token Secret metadata is unavailable'

if ((manual_node_plan)) || [[ -z "${CF_DRILL_NODE_EXECUTOR:-}" || ! -x "${CF_DRILL_NODE_EXECUTOR}" ]]; then
  render_manual_node_plan
  if ((execute)); then
    die 'CF_DRILL_NODE_EXECUTOR is unavailable; execution remains blocked'
  fi
  exit 0
fi

table="$(table_for)"
for i in 0 1; do
  node_exec "${pod_nodes[$i]}" "test -x ${CRICTL} -a -x ${CURL} -a -x /usr/bin/jq -a -x /usr/bin/readlink -a -x /usr/bin/nsenter -a -x /usr/bin/systemd-run -a -x /usr/bin/systemctl -a -x /bin/sh -a -x /bin/sleep -a -x /usr/sbin/nft" >/dev/null || die "required remote binary path missing on ${pod_nodes[$i]}"
  resolve="sudo ${CRICTL} pods --name '^${pod_names[$i]}$' -q"
  sandbox="$(node_exec "${pod_nodes[$i]}" "${resolve}")"
  [[ "${sandbox}" != *$'\n'* && "${sandbox}" =~ ^[a-f0-9]{12,64}$ ]] || die "cannot resolve one exact sandbox for ${pod_names[$i]}"
  inspect="$(node_exec "${pod_nodes[$i]}" "sudo ${CRICTL} inspectp ${sandbox}")"
  [[ "$(jq -r '.status.labels["io.kubernetes.pod.uid"]//empty' <<<"${inspect}")" == "${pod_uids[$i]}" ]] || die 'sandbox UID does not match selected pod'
  pid="$(jq -r '.info.pid//empty' <<<"${inspect}")"
  [[ "${pid}" =~ ^[1-9][0-9]*$ ]] || die 'sandbox has no exact network namespace PID'
  inode="$(node_exec "${pod_nodes[$i]}" "sudo /usr/bin/readlink /proc/${pid}/ns/net")"
  [[ "${inode}" =~ ^net:\[[0-9]+\]$ ]] || die 'cannot prove exact pod network namespace identity'
  pod_sandboxes+=("${sandbox}"); pod_pids+=("${pid}"); pod_netns+=("${inode}")
  collision_check="test \"\$(sudo ${CRICTL} inspectp ${sandbox} | /usr/bin/jq -r '.status.labels[\"io.kubernetes.pod.uid\"]')\" = '${pod_uids[$i]}' && test \"\$(sudo /usr/bin/readlink /proc/${pid}/ns/net)\" = '${inode}' && ruleset=\"\$(sudo /usr/bin/nsenter -t ${pid} -n /usr/sbin/nft -j list ruleset)\" && printf '%s\\n' \"\${ruleset}\" | /usr/bin/jq -e --arg table '${table}' '[.nftables[]?.table? | select(.family==\"inet\" and .name==\$table)] | length == 0' >/dev/null"
  node_exec "${pod_nodes[$i]}" "${collision_check}" >/dev/null || die 'owner table absence could not be proven'
done

evidence_dir="${evidence_dir:-${HOME}/operator-evidence/cloudflare-wan-dependency-loss-drill-${owner}}"
umask 077; mkdir -p "${evidence_dir}"
jq -n --arg owner "${owner}" --arg revision "${head_revision}" --arg secret "${secret_metadata}" \
  --arg expectedObservabilityRevision "${expected_observability_revision}" --arg observedObservabilityRevision "${observed_observability_revision}" \
  --argjson pods "$(for i in 0 1; do jq -n --arg name "${pod_names[$i]}" --arg uid "${pod_uids[$i]}" --arg node "${pod_nodes[$i]}" --arg sandbox "${pod_sandboxes[$i]}" --arg pid "${pod_pids[$i]}" --arg netns "${pod_netns[$i]}" --argjson restartCount "${pod_restarts[$i]}" --arg image "${EXPECTED_IMAGE}" '{name:$name,uid:$uid,node:$node,sandbox:$sandbox,pid:$pid,netns:$netns,restartCount:$restartCount,image:$image}'; done | jq -s .)" \
  --argjson deployment "$(jq -S '{metadata:{labels:.metadata.labels,annotations:.metadata.annotations,uid:.metadata.uid,resourceVersion:.metadata.resourceVersion,generation:.metadata.generation},spec:.spec,status:{observedGeneration:.status.observedGeneration}}' <<<"${deployment}")" \
  --argjson metrics "$(jq -n --arg targets "$(prom_query 'count(up{namespace="cloudflare",service="cloudflare-tunnel-metrics"} == 1)' | jq -r '.data.result[0].value[1]//"0"')" --arg ha "$(prom_query 'count(cloudflared_tunnel_ha_connections{namespace="cloudflare",service="cloudflare-tunnel-metrics"} >= 4)' | jq -r '.data.result[0].value[1]//"0"')" '{targets:$targets,ha:$ha}')" \
  '{owner:$owner,revision:$revision,observabilityRevision:{expected:$expectedObservabilityRevision,observed:$observedObservabilityRevision},secretMetadata:$secret,pods:$pods,deployment:$deployment,preflightMetrics:$metrics}' >"${evidence_dir}/preflight.json"
printf '%s\n' "${preflight_http[@]}" >"${evidence_dir}/endpoints-before.tsv"
printf '%s\n' "${cf_history}" >"${evidence_dir}/cloudflare-helm-history.json"
printf '%s\n' "${obs_history}" >"${evidence_dir}/observability-helm-history.json"

trap 'cleanup $?' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# A transient host service survives this operator process. Install all watchdogs before disruption.
for i in 0 1; do
  # Revalidate the CRI owner and inode, then enter the namespace immediately.  The
  # long-lived nsenter child pins that namespace; no delayed stored-PID lookup occurs.
  printf -v watchdog_body '%q ' /bin/sh -c "test \"\$(/usr/bin/readlink /proc/self/ns/net)\" = '${pod_netns[$i]}' || exit 70; /bin/sleep 240; /usr/sbin/nft delete table inet ${table} 2>/dev/null || true; ruleset=\"\$(/usr/sbin/nft -j list ruleset)\" || exit 71; printf '%s\\n' \"\${ruleset}\" | /usr/bin/jq -e --arg table '${table}' '[.nftables[]?.table? | select(.family==\"inet\" and .name==\$table)] | length == 0' >/dev/null"
  unit="${owner}-cleanup.service"
  watchdog="test \"\$(sudo ${CRICTL} inspectp ${pod_sandboxes[$i]} | /usr/bin/jq -r '.status.labels[\"io.kubernetes.pod.uid\"]')\" = '${pod_uids[$i]}' && test \"\$(sudo /usr/bin/readlink /proc/${pod_pids[$i]}/ns/net)\" = '${pod_netns[$i]}' && sudo /usr/bin/systemd-run --unit '${unit%.service}' --collect /usr/bin/nsenter -t ${pod_pids[$i]} -n ${watchdog_body}"
  node_exec "${pod_nodes[$i]}" "${watchdog}" >/dev/null || die "cleanup watchdog failed on ${pod_nodes[$i]}"
  watchdog_pid="$(node_exec "${pod_nodes[$i]}" "sudo /usr/bin/systemctl is-active --quiet '${unit}' && sudo /usr/bin/systemctl show --property MainPID --value '${unit}'")" || die "cleanup watchdog is inactive on ${pod_nodes[$i]}"
  [[ "${watchdog_pid}" =~ ^[1-9][0-9]*$ ]] || die "cleanup watchdog has no live MainPID on ${pod_nodes[$i]}"
  [[ "$(node_exec "${pod_nodes[$i]}" "sudo /usr/bin/readlink /proc/${watchdog_pid}/ns/net")" == "${pod_netns[$i]}" ]] || die "cleanup watchdog namespace mismatch on ${pod_nodes[$i]}"
done
for i in 0 1; do
  install="test \"\$(sudo ${CRICTL} inspectp ${pod_sandboxes[$i]} | /usr/bin/jq -r '.status.labels[\"io.kubernetes.pod.uid\"]')\" = '${pod_uids[$i]}' && test \"\$(sudo /usr/bin/readlink /proc/${pod_pids[$i]}/ns/net)\" = '${pod_netns[$i]}' && sudo /usr/bin/nsenter -t ${pod_pids[$i]} -n /usr/sbin/nft 'add table inet ${table}; add chain inet ${table} output { type filter hook output priority -10; policy accept; }; add rule inet ${table} output udp dport { 7844, 443 } counter drop comment \"${owner}\"; add rule inet ${table} output tcp dport { 7844, 443 } counter drop comment \"${owner}\"'"
  # A transport failure is ambiguous: record the attempt before the command so EXIT cleanup tries it.
  attempted_indices+=("${i}")
  if ! node_exec "${pod_nodes[$i]}" "${install}" >/dev/null; then
    cleanup 1
  fi
done

disruption_started="${SECONDS}"
deadline=$((SECONDS+90)); interrupted=0
while ((SECONDS < deadline)); do
  current="$(kubectl -n cloudflare get pods -l "${SELECTOR}" -o json)"
  unchanged="$(jq --arg u0 "${pod_uids[0]}" --arg u1 "${pod_uids[1]}" --argjson r0 "${pod_restarts[0]}" --argjson r1 "${pod_restarts[1]}" '
    [.items[]|select(.metadata.deletionTimestamp==null)] as $p | ($p|length)==2 and
    ([$p[].metadata.uid]|sort)==([$u0,$u1]|sort) and
    all($p[];([.status.containerStatuses[].restartCount]|add)==(if .metadata.uid==$u0 then $r0 else $r1 end))' <<<"${current}")"
  same="$(jq 'all(.items[]; any(.status.conditions[]?;.type=="Ready" and .status=="False"))' <<<"${current}")"
  ready_results=()
  ready_queries_ok=1
  for i in 0 1; do
    ready_command="test \"\$(sudo ${CRICTL} inspectp ${pod_sandboxes[$i]} | /usr/bin/jq -r '.status.labels[\"io.kubernetes.pod.uid\"]')\" = '${pod_uids[$i]}' && test \"\$(sudo /usr/bin/readlink /proc/${pod_pids[$i]}/ns/net)\" = '${pod_netns[$i]}' && sudo /usr/bin/nsenter -t ${pod_pids[$i]} -n /bin/sh -c 'body=\"\$(${CURL} -sS --max-time 5 -w \"\\n%{http_code}\" http://127.0.0.1:2000/ready)\" || exit 81; status=\"\${body##*\n}\"; payload=\"\${body%\n*}\"; printf \"%s\" \"\${payload}\" | /usr/bin/jq -ce --argjson status \"\${status}\" '\"'\"'{httpStatus:\$status,readyConnections:(.readyConnections | select(type==\"number\" and floor==. and .>=0))}'\"'\"' '"
    if ready_result="$(node_exec "${pod_nodes[$i]}" "${ready_command}" 2>/dev/null)" &&
      jq -e 'keys == ["httpStatus","readyConnections"]' <<<"${ready_result}" >/dev/null 2>&1; then
      ready_results+=("${ready_result}")
    else
      ready_queries_ok=0
      ready_results+=('{"httpStatus":null,"readyConnections":null}')
    fi
  done
  target_raw="$(prom_query 'count(up{namespace="cloudflare",service="cloudflare-tunnel-metrics"} == 1)' 2>/dev/null || true)"
  target_count="$(jq -er '.data.result[0].value[1] | tonumber' <<<"${target_raw}" 2>/dev/null || printf '%s' -1)"
  ha_raw="$(prom_query 'cloudflared_tunnel_ha_connections{namespace="cloudflare",service="cloudflare-tunnel-metrics"}' 2>/dev/null || true)"
  ha_values="$(jq -ec '[.data.result[]?.value[1] | tonumber] | sort' <<<"${ha_raw}" 2>/dev/null || printf '[]')"
  elapsed=$((SECONDS-disruption_started))
  jq -cn --argjson elapsed "${elapsed}" --argjson pods "$(jq -c '[.items[] | {uid:.metadata.uid,restartCount:([.status.containerStatuses[].restartCount]|add),ready:([.status.conditions[]?|select(.type=="Ready")][0].status//null)}] | sort_by(.uid)' <<<"${current}")" --argjson ready "$(printf '%s\n' "${ready_results[@]}" | jq -s .)" --argjson targets "${target_count}" --argjson ha "${ha_values}" '{elapsedSeconds:$elapsed,pods:$pods,readyEndpoints:$ready,prometheusTargetCount:$targets,haConnections:$ha}' >>"${evidence_dir}/interruption-observations.jsonl"
  [[ "${unchanged}" == true ]] || die 'connector UID/restart set changed during interruption'
  ((ready_queries_ok)) || die 'connector readiness endpoint was unavailable or malformed during interruption'
  [[ "${target_count}" == 2 ]] || die 'Prometheus target became unavailable during interruption'
  ready_zero="$(printf '%s\n' "${ready_results[@]}" | jq -s 'length==2 and all(.[];.httpStatus==503 and .readyConnections==0)')"
  if [[ "${same}" == true && "${ready_zero}" != true ]]; then
    die 'a NotReady connector still reports ready connections'
  fi
  [[ "${same}" == true && "${ready_zero}" == true ]] && { interrupted=1; break; }
  sleep 5
done
((interrupted)) || die 'did not prove same-process NotReady and zero ready connections'
remaining=$((DISRUPTION_SECONDS-(SECONDS-disruption_started)))
if ((remaining > 0)); then sleep "${remaining}"; fi

# Remove only the two exact drill-owned tables now; EXIT cleanup remains a second attempt.
cleanup_failed=0
declare -a cleanup_retry_indices=()
for i in "${attempted_indices[@]}"; do
  delete_and_prove="test \"\$(sudo ${CRICTL} inspectp ${pod_sandboxes[$i]} | /usr/bin/jq -r '.status.labels[\"io.kubernetes.pod.uid\"]')\" = '${pod_uids[$i]}' && test \"\$(sudo /usr/bin/readlink /proc/${pod_pids[$i]}/ns/net)\" = '${pod_netns[$i]}' && { sudo /usr/bin/nsenter -t ${pod_pids[$i]} -n /usr/sbin/nft delete table inet ${table} 2>/dev/null || true; } && ruleset=\"\$(sudo /usr/bin/nsenter -t ${pod_pids[$i]} -n /usr/sbin/nft -j list ruleset)\" && printf '%s\\n' \"\${ruleset}\" | /usr/bin/jq -e --arg table '${table}' '[.nftables[]?.table? | select(.family==\"inet\" and .name==\$table)] | length == 0' >/dev/null"
  if ! node_exec "${pod_nodes[$i]}" "${delete_and_prove}" >/dev/null; then
    cleanup_failed=1
    cleanup_retry_indices+=("${i}")
  fi
done
attempted_indices=("${cleanup_retry_indices[@]}")
((cleanup_failed==0)) || { manual_cleanup; die 'automated exact cleanup could not be proven'; }

deadline=$((SECONDS+RECOVERY_SECONDS)); recovered=0
while ((SECONDS < deadline)); do
  current="$(kubectl -n cloudflare get pods -l "${SELECTOR}" -o json)"
  unchanged="$(jq --arg u0 "${pod_uids[0]}" --arg u1 "${pod_uids[1]}" --argjson r0 "${pod_restarts[0]}" --argjson r1 "${pod_restarts[1]}" '[.items[]|select(.metadata.deletionTimestamp==null)] as $p | ($p|length)==2 and ([$p[].metadata.uid]|sort)==([$u0,$u1]|sort) and all($p[];([.status.containerStatuses[].restartCount]|add)==(if .metadata.uid==$u0 then $r0 else $r1 end))' <<<"${current}")"
  [[ "${unchanged}" == true ]] || die 'connector UID/restart set changed during recovery'
  if jq -e --arg u0 "${pod_uids[0]}" --arg u1 "${pod_uids[1]}" --argjson r0 "${pod_restarts[0]}" --argjson r1 "${pod_restarts[1]}" '
    [.items[]|select(.metadata.uid==$u0 or .metadata.uid==$u1)] as $p | ($p|length)==2 and
    all($p[];([.status.containerStatuses[].restartCount]|add)==(if .metadata.uid==$u0 then $r0 else $r1 end)) and
    all($p[];any(.status.conditions[]?;.type=="Ready" and .status=="True"))' <<<"${current}" >/dev/null &&
    [[ "$(prom_query 'count(cloudflared_tunnel_ha_connections{namespace="cloudflare",service="cloudflare-tunnel-metrics"} >= 4)' | jq -r '.data.result[0].value[1]//"0"')" == 2 ]]; then recovered=1; break; fi
  sleep 5
done
((recovered)) || die 'same-pod recovery with unchanged restart counts was not proven within five minutes'
for endpoint in "${endpoints[@]}"; do
  code="$(${http_command} -fsS -o /dev/null -w '%{http_code}' --max-time 15 "${endpoint}")"
  printf '%s\t%s\n' "${endpoint}" "${code}" >>"${evidence_dir}/endpoints-after.tsv"
  [[ "${code}" == 200 ]] || die "endpoint did not recover: ${endpoint}"
done
prom_query 'count(cloudflared_tunnel_ha_connections{namespace="cloudflare",service="cloudflare-tunnel-metrics"} >= 4)' >"${evidence_dir}/recovery-metrics.json"
[[ "$(kubectl -n cloudflare get secret tunnel-token -o jsonpath='{.metadata.uid}{"\t"}{.metadata.resourceVersion}{"\t"}{.metadata.creationTimestamp}{"\n"}')" == "${secret_metadata}" ]] || die 'Secret metadata changed'
[[ "$(helm -n cloudflare history cloudflare-tunnel -o json)" == "${cf_history}" ]] || die 'Cloudflare Helm history changed'
recovery_obs_history="$(helm -n monitoring history kube-prometheus-stack -o json)"
validate_observability_history "${recovery_obs_history}" 'post-cleanup'
[[ "${recovery_obs_history}" == "${obs_history}" ]] || die "observability Helm history changed (expected deployed revision ${expected_observability_revision}; observed ${observed_observability_revision})"
final_deployment="$(kubectl -n cloudflare get deployment cloudflare-tunnel -o json)"
[[ "$(jq -S '{metadata:{labels:.metadata.labels,annotations:.metadata.annotations,uid:.metadata.uid,generation:.metadata.generation},spec:.spec}' <<<"${final_deployment}" | sha256sum | cut -d' ' -f1)" == "${deployment_fingerprint}" ]] || die 'Deployment desired or ownership state changed'
[[ "$(jq -r '.status.observedGeneration' <<<"${final_deployment}")" == "${deployment_generation}" ]] || die 'Deployment has not observed its unchanged generation'
just cf-tunnel-verify env=staging
printf 'PASS: same cloudflared processes recovered; observability revision expected=%s observed=%s; sanitized evidence: %s\n' "${expected_observability_revision}" "${observed_observability_revision}" "${evidence_dir}"
