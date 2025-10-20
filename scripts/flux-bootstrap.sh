#!/usr/bin/env bash
# shellcheck disable=SC2086
set -euo pipefail

# flux-bootstrap.sh: idempotent helper to bootstrap Flux onto a new cluster.
#
# Requirements:
#   * flux CLI installed locally
#   * kubectl context pointing at the target cluster
#   * AGE secret material prepared as ./secrets/flux-system/sops-age.enc.yaml
#
# Usage:
#   scripts/flux-bootstrap.sh --cluster dev --git-url ssh://git@github.com/example/sugarkube-platform.git
#
# The script will:
#   1. Create the flux-system namespace if missing
#   2. Apply the bootstrap components
#   3. Configure the GitRepository/Kustomization sync
#   4. Re-apply to ensure idempotency

CLUSTER="dev"
GIT_URL=""
BRANCH="main"
PATH_ROOT="./clusters"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cluster)
      CLUSTER="$2"
      shift 2
      ;;
    --git-url)
      GIT_URL="$2"
      shift 2
      ;;
    --branch)
      BRANCH="$2"
      shift 2
      ;;
    --path-root)
      PATH_ROOT="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$GIT_URL" ]]; then
  echo "--git-url is required" >&2
  exit 1
fi

if ! command -v flux >/dev/null 2>&1; then
  echo "flux CLI is required" >&2
  exit 1
fi

kubectl create namespace flux-system --dry-run=client -o yaml | kubectl apply -f -

flux install --namespace flux-system --components-extra image-reflector-controller,image-automation-controller --export \
  | kubectl apply -f -

kubectl apply -f flux/gotk-components.yaml

kubectl apply -f flux/gotk-sync.yaml

flux create secret git flux-system --url "$GIT_URL" --ssh-username git --export \
  | kubectl apply -f -

kubectl patch gitrepository flux-system -n flux-system --type merge \
  --patch "{\"spec\":{\"url\":\"$GIT_URL\",\"ref\":{\"branch\":\"$BRANCH\"}}}"

kubectl patch kustomization flux-system -n flux-system --type merge \
  --patch "{\"spec\":{\"path\":\"$PATH_ROOT/$CLUSTER\"}}"

# Ensure the SOPS age secret exists (requires decrypted material available locally).
if [[ -f "secrets/flux-system/sops-age.yaml" ]]; then
  kubectl apply -f secrets/flux-system/sops-age.yaml
else
  echo "INFO: secrets/flux-system/sops-age.yaml not found. Create it with 'sops --encrypt' before bootstrap." >&2
fi

flux reconcile source git flux-system --namespace flux-system --with-source
flux reconcile kustomization flux-system --namespace flux-system --with-source
