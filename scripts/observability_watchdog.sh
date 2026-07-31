#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE=monitoring
SECRET=alertmanager-healthchecks-watchdog
TTY="${SUGARKUBE_WATCHDOG_TTY:-/dev/tty}"
usage() { echo "Usage: $0 <install-secret|check-secret|verify|silence-create|silence-status|silence-clear> env=staging" >&2; exit 2; }
die() { printf 'ERROR: %s\n' "$1" >&2; exit "${2:-1}"; }
normalize_env() { local e="${1:-}"; while [[ "$e" == env=* ]]; do e="${e#env=}"; done; [[ "$e" == staging ]] || die "env=staging is required; production and unknown environments are unsupported." 2; }
context_guard() { [[ "$(kubectl config current-context 2>/dev/null || true)" == sugar-staging ]] || die "expected Kubernetes context sugar-staging before staging mutation." 3; python3 "$ROOT/scripts/cluster_identity.py" assert --kubeconfig "${KUBECONFIG:-$HOME/.kube/config}" --env staging >/dev/null; }
check_secret() { context_guard; local found; found="$(kubectl -n "$NAMESPACE" get secret "$SECRET" -o 'go-template={{if index .data "ping-url"}}present{{end}}' 2>/dev/null)" || die "watchdog Secret is absent (value not accessed)." 15; [[ "$found" == present ]] || die "watchdog Secret ping-url is missing or empty (value not accessed)." 15; echo "Watchdog Secret contract exists (value not accessed or displayed)."; }
install_secret() {
  context_guard
  [[ -z "${HEALTHCHECKS_PING_URL:-}${HEALTHCHECK_PING_URL:-}${PING_URL:-}${WATCHDOG_PING_URL:-}" ]] || die "credential environment variables are refused."
  [[ $# == 0 ]] || die "credential arguments are refused."
  exec 3<"$TTY"; [[ "${SUGARKUBE_WATCHDOG_TEST_NONTTY:-0}" == 1 || -t 3 ]] || die "an interactive controlling terminal is required."
  printf 'Enter the Healthchecks watchdog ping URL (input hidden): ' >&2
  IFS= read -r -s value <&3 || die "could not read the ping URL (value redacted)."; printf '\n' >&2
  [[ "$value" =~ ^https://hc-ping\.com/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ && "$value" != *$'\n'* ]] || die "ping URL is invalid (value redacted)."
  if ! kubectl -n "$NAMESPACE" create secret generic "$SECRET" --from-file=ping-url=/dev/stdin --dry-run=client -o yaml <<<"$value" | kubectl apply -f - >/dev/null; then
    unset value; die "watchdog Secret installation failed (value redacted)."
  fi
  unset value
  echo "Watchdog Secret installed or rotated (value not displayed)."
}
verify() {
  context_guard; check_secret
  local p a cr cfg
  p="$(mktemp)"; a="$(mktemp)"; cr="$(mktemp)"; cfg="$(mktemp)"; trap 'rm -f "$p" "$a" "$cr" "$cfg"' EXIT
  kubectl get --raw "/api/v1/namespaces/$NAMESPACE/services/http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/rules" >"$p"
  kubectl get --raw "/api/v1/namespaces/$NAMESPACE/services/http:kube-prometheus-stack-alertmanager:9093/proxy/api/v2/alerts" >"$a"
  python3 - "$p" "$a" <<'PY'
import json,sys
p,a=(json.load(open(x)) for x in sys.argv[1:])
wanted={"alertname":"SugarkubeObservabilityWatchdog","environment":"staging","cluster":"sugarkube-int","purpose":"observability-watchdog"}
rules=[r for g in p.get("data",{}).get("groups",[]) for r in g.get("rules",[]) if r.get("name")==wanted["alertname"]]
if len(rules)!=1 or rules[0].get("state")!="firing" or any(rules[0].get("labels",{}).get(k)!=v for k,v in wanted.items() if k!="alertname"):
 raise SystemExit("ERROR: exact watchdog Prometheus rule is not firing (output redacted).")
alerts=[x for x in a if all(x.get("labels",{}).get(k)==v for k,v in wanted.items()) and x.get("status",{}).get("state")=="active"]
if len(alerts)!=1: raise SystemExit("ERROR: exact watchdog alert is not active in Alertmanager (output redacted).")
PY
  kubectl -n "$NAMESPACE" get alertmanager kube-prometheus-stack-alertmanager -o yaml >"$cr"
  kubectl -n "$NAMESPACE" get secret alertmanager-kube-prometheus-stack-alertmanager -o yaml >"$cfg"
  ruby "$ROOT/scripts/verify_observability_alertmanager.rb" live "$cr" "$cfg"
  kubectl -n "$NAMESPACE" logs statefulset/alertmanager-kube-prometheus-stack-alertmanager --since=6m | python3 -c 'import re,sys; s=sys.stdin.read(); raise SystemExit("ERROR: watchdog webhook delivery errors observed (details redacted).") if re.search(r"(?i)(watchdog|healthchecks).*(error|failed)|(?:error|failed).*(watchdog|healthchecks)",s) else None'
  echo "Watchdog rule, active alert, mounted receiver contract, and bounded delivery logs verified; credentials were not accessed."
}
silence_create() {
  context_guard
  cat >&2 <<'EOF'
MANUAL CHECKPOINT: confirm Healthchecks currently shows a recent successful watchdog ping before disruption. This command creates only an eight-minute silence; it never stops nodes or pings Healthchecks.
EOF
  python3 -c 'import json; from datetime import datetime,timedelta,timezone; now=datetime.now(timezone.utc); f=lambda d:d.isoformat(timespec="seconds").replace("+00:00","Z"); print(json.dumps({"matchers":[{"name":k,"value":v,"isRegex":False} for k,v in [("alertname","SugarkubeObservabilityWatchdog"),("environment","staging"),("cluster","sugarkube-int"),("purpose","observability-watchdog")]],"startsAt":f(now),"endsAt":f(now+timedelta(minutes=8)),"createdBy":"sugarkube-observability-watchdog-drill","comment":"Owned staging watchdog failure drill"}))' | kubectl create --raw "/api/v1/namespaces/$NAMESPACE/services/http:kube-prometheus-stack-alertmanager:9093/proxy/api/v2/silences" -f - | python3 -c 'import json,sys; d=json.load(sys.stdin); print("Owned watchdog drill silence created; id="+d["silenceID"]+"; automatic expiry=8m.")'
}
owned_silences() { kubectl get --raw "/api/v1/namespaces/$NAMESPACE/services/http:kube-prometheus-stack-alertmanager:9093/proxy/api/v2/silences" | python3 -c 'import json,sys; wanted={"alertname":"SugarkubeObservabilityWatchdog","environment":"staging","cluster":"sugarkube-int","purpose":"observability-watchdog"}; print("\n".join(x["id"] for x in json.load(sys.stdin) if x.get("createdBy")=="sugarkube-observability-watchdog-drill" and {m["name"]:m["value"] for m in x.get("matchers",[])}==wanted and x.get("status",{}).get("state") in ("active","pending")))'; }
silence_status() { context_guard; ids="$(owned_silences)"; [[ -n "$ids" ]] && printf 'Owned active/pending watchdog drill silence IDs:\n%s\n' "$ids" || echo "No owned active watchdog drill silence."; }
silence_clear() { context_guard; ids="$(owned_silences)"; [[ -n "$ids" ]] || { echo "No owned active watchdog drill silence to clear."; return; }; while IFS= read -r id; do kubectl delete --raw "/api/v1/namespaces/$NAMESPACE/services/http:kube-prometheus-stack-alertmanager:9093/proxy/api/v2/silence/$id" >/dev/null; done <<<"$ids"; echo "Owned watchdog drill silence cleared."; }
cmd="${1:-}"; shift || true; env_arg="${1:-}"; shift || true; normalize_env "$env_arg"
case "$cmd" in install-secret) install_secret "$@";; check-secret) check_secret;; verify) verify;; silence-create) silence_create;; silence-status) silence_status;; silence-clear) silence_clear;; *) usage;; esac
