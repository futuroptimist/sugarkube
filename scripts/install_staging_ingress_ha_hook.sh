#!/usr/bin/env bash
# Install/remove the post-k3s-start reconciliation hook on a staging server.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ACTION=${1:-}
ENVIRONMENT=${2:-}
DEST=/usr/local/libexec/sugarkube-staging-ingress-ha
CONFIG=/etc/sugarkube/staging-ingress-ha
DROPIN=/etc/systemd/system/k3s.service.d/30-staging-ingress-ha.conf

[[ ${ENVIRONMENT#env=} == staging ]] || { echo "ERROR: hook mutation requires env=staging" >&2; exit 2; }
[[ $(kubectl config current-context) == sugar-staging ]] || { echo "ERROR: expected Kubernetes context sugar-staging" >&2; exit 3; }
[[ $EUID -eq 0 ]] || { echo "ERROR: rerun hook installation with sudo while preserving KUBECONFIG" >&2; exit 4; }

case "$ACTION" in
  install)
    install -d -m 0755 "$DEST" "$CONFIG" "$(dirname "$DROPIN")"
    install -m 0755 "$ROOT/scripts/staging_ingress_ha.py" "$DEST/staging_ingress_ha.py"
    install -m 0644 "$ROOT/clusters/staging/platform-ha/"*.yaml "$CONFIG/"
    cat >"$DROPIN" <<EOF
[Service]
ExecStartPost=/usr/bin/env SUGARKUBE_HA_CONFIG=$CONFIG KUBECONFIG=${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml} $DEST/staging_ingress_ha.py reconcile staging
EOF
    systemctl daemon-reload
    echo "Installed post-start reconciliation hook; k3s was not restarted."
    ;;
  remove)
    rm -f "$DROPIN"
    rm -rf "$DEST" "$CONFIG"
    systemctl daemon-reload
    echo "Removed post-start reconciliation hook; k3s was not restarted."
    ;;
  *) echo "usage: $0 install|remove env=staging" >&2; exit 2 ;;
esac
