#!/usr/bin/env bash
# Explicit, staging-only mutating rollout. Never called by CI.
set -Eeuo pipefail
[[ "${1:-}" == "--confirm-staging" ]] || { echo "Usage: $0 --confirm-staging" >&2; exit 2; }
[[ "$(kubectl config current-context)" == sugar-staging ]] || { echo "ERROR: expected sugar-staging context." >&2; exit 3; }
python3 scripts/cluster_identity.py assert --env staging >/dev/null
mapfile -t releases < <(helm -n cloudflare list --filter '^cloudflare-tunnel$' -q)
[[ ${#releases[@]} == 1 && "${releases[0]}" == cloudflare-tunnel ]] || { echo "ERROR: expected one existing cloudflare-tunnel release." >&2; exit 4; }
[[ "$(helm -n cloudflare status cloudflare-tunnel -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)["chart"])')" == cloudflare-tunnel-0.3.2 ]] || { echo "ERROR: unexpected chart ownership/version." >&2; exit 4; }
kubectl -n cloudflare get secret tunnel-token -o 'go-template={{if index .data "token"}}present{{end}}' | grep -qx present
kubectl apply -k platform/cloudflare-tunnel
kubectl -n cloudflare patch deployment cloudflare-tunnel --type json --patch-file platform/cloudflare-tunnel/deployment-patch.json
kubectl -n cloudflare rollout status deployment/cloudflare-tunnel --timeout=5m
python3 scripts/verify_cloudflare_tunnel.py
