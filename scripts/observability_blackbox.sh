#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASE="prometheus-blackbox-exporter"
BASE_RELEASE="kube-prometheus-stack"
NAMESPACE="monitoring"
CHART="prometheus-community/prometheus-blackbox-exporter"
REPOSITORY="https://prometheus-community.github.io/helm-charts"
VERSION_FILE="${ROOT}/platform/observability/helm/prometheus-blackbox-exporter.version"
STAGING_VALUES="${ROOT}/clusters/staging/observability/prometheus-blackbox-exporter.values.yaml"
PROBES="${ROOT}/clusters/staging/observability/probes"
TIMEOUT="${SUGARKUBE_OBSERVABILITY_HELM_TIMEOUT:-20m}"
PROMETHEUS_SERVICE="kube-prometheus-stack-prometheus"

usage() { echo "Usage: $0 <render|install|upgrade|status|verify> env=staging" >&2; }
normalize_env() { local raw="${1:-}"; while [[ "$raw" == env=* ]]; do raw="${raw#env=}"; done; case "$raw" in int) echo "WARNING: env name 'int' is deprecated; using env=staging." >&2; printf staging;; staging) printf staging;; ""|prod|production) echo "ERROR: production blackbox observability is not supported; pass env=staging explicitly." >&2; exit 2;; *) echo "ERROR: unsupported blackbox observability env '$raw'; supported env: staging." >&2; exit 2;; esac; }
require_tools() { for tool in "$@"; do command -v "$tool" >/dev/null || { echo "ERROR: required tool missing: $tool" >&2; exit 127; }; done; }
version() { tr -d '[:space:]' <"$VERSION_FILE"; }
current_context() { kubectl config current-context 2>/dev/null || true; }
print_resolved() { cat <<EOT
blackbox environment: staging
current Kubernetes context: $(current_context || true)
namespace: ${NAMESPACE}
release: ${RELEASE}
chart: ${CHART}
chart repository: ${REPOSITORY}
pinned version: $(version)
ordered values files:
  - ${STAGING_VALUES}
Probe manifest path: ${PROBES}
EOT
}
assert_context() { local ctx; ctx="$(current_context)"; [[ "$ctx" == sugar-staging ]] || { echo "ERROR: context mismatch: expected 'sugar-staging', got '${ctx:-<none>}' before mutation." >&2; exit 3; }; python3 "$ROOT/scripts/cluster_identity.py" assert --kubeconfig "${KUBECONFIG:-${HOME}/.kube/config}" --env staging >/dev/null; }
render_to() { local chart_out="$1" probes_out="$2"; helm repo add prometheus-community "$REPOSITORY" --force-update >/dev/null; helm repo update prometheus-community >/dev/null; helm template "$RELEASE" "$CHART" --namespace "$NAMESPACE" --version "$(version)" -f "$STAGING_VALUES" >"$chart_out"; kubectl kustomize "$PROBES" >"$probes_out"; [[ -s "$chart_out" && -s "$probes_out" ]]; }
release_state() { local matches; matches="$(helm list --namespace "$NAMESPACE" --all --filter "^${RELEASE}$" --short)" || { echo "ERROR: Helm could not query exporter release state; refusing to mutate." >&2; return 1; }; if [[ "$matches" == "$RELEASE" ]]; then printf present; elif [[ -z "$matches" ]]; then printf absent; else echo "ERROR: unexpected Helm release query result." >&2; return 1; fi; }
preflight() { helm status "$BASE_RELEASE" --namespace "$NAMESPACE" >/dev/null || { echo "ERROR: canonical ${BASE_RELEASE} release is required." >&2; return 1; }; kubectl get crd probes.monitoring.coreos.com servicemonitors.monitoring.coreos.com >/dev/null; kubectl -n "$NAMESPACE" get service "$PROMETHEUS_SERVICE" >/dev/null; }
with_rendered() { CHART_RENDER="$(mktemp -t sugarkube-blackbox-chart.XXXXXX.yaml)"; PROBE_RENDER="$(mktemp -t sugarkube-blackbox-probes.XXXXXX.yaml)"; trap 'rm -f "${CHART_RENDER:-}" "${PROBE_RENDER:-}"' EXIT; render_to "$CHART_RENDER" "$PROBE_RENDER"; }
render() { require_tools helm kubectl; print_resolved; with_rendered; cat "$CHART_RENDER"; printf '%s\n' '---'; cat "$PROBE_RENDER"; }
mutate() { local operation="$1" state; require_tools helm kubectl python3; print_resolved; assert_context; with_rendered; preflight; state="$(release_state)"; if [[ "$operation" == install && "$state" == present ]]; then echo "ERROR: exporter already exists; use observability-blackbox-upgrade." >&2; exit 4; fi; if [[ "$operation" == upgrade && "$state" == absent ]]; then echo "ERROR: exporter is absent; use observability-blackbox-install." >&2; exit 5; fi; if [[ "$operation" == install ]]; then helm install "$RELEASE" "$CHART" --namespace "$NAMESPACE" --version "$(version)" -f "$STAGING_VALUES" --wait --timeout "$TIMEOUT"; else helm upgrade "$RELEASE" "$CHART" --namespace "$NAMESPACE" --version "$(version)" -f "$STAGING_VALUES" --wait --timeout "$TIMEOUT"; fi; kubectl apply -f "$PROBE_RENDER"; }
status() { require_tools helm kubectl python3; print_resolved; assert_context; helm status "$RELEASE" -n "$NAMESPACE"; kubectl -n "$NAMESPACE" get deployment,pod,service -l "app.kubernetes.io/instance=${RELEASE}"; kubectl -n "$NAMESPACE" get servicemonitor "$RELEASE"; kubectl -n "$NAMESPACE" get probe -l 'release=kube-prometheus-stack,environment=staging' -L app,route,criticality; }
validate_objects() { kubectl -n "$NAMESPACE" rollout status "deployment/${RELEASE}" --timeout="$TIMEOUT"; [[ "$(kubectl -n "$NAMESPACE" get service "$RELEASE" -o jsonpath='{.spec.type}')" == ClusterIP ]] || { echo 'ERROR: exporter Service must be ClusterIP.' >&2; return 6; }; [[ -z "$(kubectl -n "$NAMESPACE" get ingress -l "app.kubernetes.io/instance=${RELEASE}" -o name)" ]] || { echo 'ERROR: exporter Ingress exists.' >&2; return 6; }; [[ -z "$(kubectl -n "$NAMESPACE" get service -l "app.kubernetes.io/instance=${RELEASE}" -o jsonpath='{range .items[*].spec.ports[*]}{.nodePort}{"\n"}{end}' | sed '/^$/d')" ]] || { echo 'ERROR: exporter NodePort exists.' >&2; return 6; }; [[ "$(kubectl -n "$NAMESPACE" get servicemonitor "$RELEASE" -o jsonpath='{.metadata.labels.release}')" == "$BASE_RELEASE" ]] || { echo "ERROR: exporter ServiceMonitor must have release: ${BASE_RELEASE}." >&2; return 7; }; kubectl -n "$NAMESPACE" get probe -o json | python3 -c "$PROBE_VALIDATOR"; }
read -r -d '' PROBE_VALIDATOR <<'PY' || true
import json,sys
expected={('dspace','root'),('dspace','config'),('dspace','healthz'),('dspace','livez'),('tokenplace','root'),('tokenplace','healthz'),('tokenplace','livez'),('tokenplace','metadata'),('danielsmith','root'),('danielsmith','healthz'),('danielsmith','livez'),('jobbot3000','root'),('jobbot3000','healthz'),('jobbot3000','livez'),('jobbot3000','tracker'),('jobbot3000','manifest')}
data=json.load(sys.stdin); items=data.get('items') if isinstance(data,dict) else None
if not isinstance(items,list): raise SystemExit('ERROR: invalid Probe response.')
owned=[]
for item in items:
 labels=item.get('metadata',{}).get('labels',{})
 name=item.get('metadata',{}).get('name','')
 if name.startswith('blackbox-') and labels.get('release')=='kube-prometheus-stack' and labels.get('environment') in ('staging','production','prod'):
  if labels.get('environment')!='staging': raise SystemExit('ERROR: lifecycle-owned production Probe exists.')
  owned.append((labels.get('app'),labels.get('route')))
if len(owned)!=16 or set(owned)!=expected or len(set(owned))!=16: raise SystemExit('ERROR: staging Probe app/route matrix is missing, unexpected, or mislabelled.')
PY
prometheus_get() { kubectl get --request-timeout=14s --raw "/api/v1/namespaces/${NAMESPACE}/services/http:${PROMETHEUS_SERVICE}:9090/proxy$1"; }
verify_series() { local attempts="${SUGARKUBE_BLACKBOX_VERIFY_ATTEMPTS:-20}" interval="${SUGARKUBE_BLACKBOX_VERIFY_INTERVAL_SECONDS:-15}" response code; [[ "$attempts" =~ ^[1-9][0-9]*$ && "$interval" =~ ^[1-9][0-9]*$ ]] || { echo 'ERROR: verification attempts and interval must be positive integers.' >&2; return 8; }; for ((n=1;n<=attempts;n++)); do response="$(prometheus_get '/api/v1/query?query=%7B__name__%3D~%22probe_success%7Cprobe_duration_seconds%7Cprobe_http_status_code%7Cprobe_dns_lookup_time_seconds%7Cprobe_ssl_earliest_cert_expiry_seconds%22%2Cenvironment%3D%22staging%22%7D')" || { echo 'ERROR: Prometheus API transport failed.' >&2; return 9; }; code=0; FINAL_ATTEMPT="$((n==attempts))" python3 -c "$SERIES_VALIDATOR" <<<"$response" || code=$?; case "$code" in 0) echo 'All 16 staging blackbox targets and required metric families are healthy.'; return;; 10) ((n<attempts)) && { echo "Blackbox series are converging (attempt ${n}/${attempts}); retrying." >&2; sleep "$interval"; };; *) return "$code";; esac; done; return 10; }
read -r -d '' SERIES_VALIDATOR <<'PY' || true
import json,os,sys
expected={(a,r) for a,r in [('dspace','root'),('dspace','config'),('dspace','healthz'),('dspace','livez'),('tokenplace','root'),('tokenplace','healthz'),('tokenplace','livez'),('tokenplace','metadata'),('danielsmith','root'),('danielsmith','healthz'),('danielsmith','livez'),('jobbot3000','root'),('jobbot3000','healthz'),('jobbot3000','livez'),('jobbot3000','tracker'),('jobbot3000','manifest')]}
families={'probe_success','probe_duration_seconds','probe_http_status_code','probe_dns_lookup_time_seconds','probe_ssl_earliest_cert_expiry_seconds'}
try: data=json.load(sys.stdin)
except (ValueError,UnicodeError): raise SystemExit('ERROR: Prometheus response is malformed JSON.')
if not isinstance(data,dict) or data.get('status')!='success': raise SystemExit('ERROR: Prometheus API response was unsuccessful.')
result=data.get('data',{}).get('result')
if not isinstance(result,list): raise SystemExit('ERROR: Prometheus API response has an invalid structure.')
seen={}; present=set()
for row in result:
 if not isinstance(row,dict) or not isinstance(row.get('metric'),dict) or not isinstance(row.get('value'),list): raise SystemExit('ERROR: Prometheus API result is invalid.')
 m=row['metric']; key=(m.get('app'),m.get('route')); name=m.get('__name__')
 if key in expected and name in families:
  present.add(name); seen.setdefault(key,{})[name]=row['value'][1] if len(row['value'])>1 else None
ok=set(seen)==expected and present==families and all(v.get('probe_success')=='1' for v in seen.values())
if ok: raise SystemExit(0)
if os.environ.get('FINAL_ATTEMPT')=='1':
 print('ERROR: staging blackbox series did not converge before timeout.',file=sys.stderr)
 for app,route in sorted(expected):
  health='up' if seen.get((app,route),{}).get('probe_success')=='1' else 'missing-or-down'
  print(f'blackbox diagnostic: app={app} environment=staging route={route} health={health} error=<redacted>',file=sys.stderr)
 missing=sorted(families-present)
 if missing: print('missing metric families: '+', '.join(missing),file=sys.stderr)
raise SystemExit(10)
PY
verify_targets() { local response; response="$(prometheus_get '/api/v1/targets?state=active')" || { echo 'ERROR: Prometheus targets API transport failed.' >&2; return 9; }; python3 -c 'import json,sys
expected={(a,r) for a,r in [("dspace","root"),("dspace","config"),("dspace","healthz"),("dspace","livez"),("tokenplace","root"),("tokenplace","healthz"),("tokenplace","livez"),("tokenplace","metadata"),("danielsmith","root"),("danielsmith","healthz"),("danielsmith","livez"),("jobbot3000","root"),("jobbot3000","healthz"),("jobbot3000","livez"),("jobbot3000","tracker"),("jobbot3000","manifest")]}
try: data=json.load(sys.stdin)
except (ValueError,UnicodeError): raise SystemExit("ERROR: Prometheus targets response is malformed JSON.")
if not isinstance(data,dict) or data.get("status")!="success": raise SystemExit("ERROR: Prometheus targets API response was unsuccessful.")
targets=data.get("data",{}).get("activeTargets")
if not isinstance(targets,list): raise SystemExit("ERROR: Prometheus targets API response has an invalid structure.")
seen={}
for target in targets:
 if not isinstance(target,dict) or not isinstance(target.get("labels"),dict): raise SystemExit("ERROR: Prometheus targets API result is invalid.")
 labels=target["labels"]; key=(labels.get("app"),labels.get("route"))
 if labels.get("environment")=="staging" and key in expected: seen[key]=target.get("health")
if set(seen)!=expected or not all(value=="up" for value in seen.values()): raise SystemExit("ERROR: expected staging Probe targets are missing or down; error=<redacted>.")' <<<"$response"; }
verify() { require_tools helm kubectl python3 sleep; print_resolved; assert_context; preflight; validate_objects; verify_series; verify_targets; }
cmd="${1:-}"; shift || true; [[ -n "$cmd" ]] || { usage; exit 2; }; normalize_env "${1:-}" >/dev/null
case "$cmd" in render) render;; install|upgrade) mutate "$cmd";; status) status;; verify) verify;; *) usage; exit 2;; esac
