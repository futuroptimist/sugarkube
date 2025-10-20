#!/usr/bin/env bash
set -euo pipefail

# This helper wraps the manual bootstrap procedure documented in docs/runbook.md.
# It is idempotent: rerunning the script reconciles the desired state without
# recreating resources that are already present. The script expects `flux` to be
# installed on the invoking machine and the kubeconfig to point at the target
# cluster.

REPO_URL="${FLUX_REPO_URL:-ssh://git@github.com/example/sugarkube-platform.git}"
BRANCH="${FLUX_REPO_BRANCH:-main}"
CLUSTER_PATH="${FLUX_CLUSTER_PATH:-clusters/dev}"

log() {
  printf '==> %s\n' "$*"
}

ensure_namespace() {
  if ! kubectl get namespace flux-system >/dev/null 2>&1; then
    log "Creating flux-system namespace"
    kubectl create namespace flux-system
  else
    log "flux-system namespace already exists"
  fi
}

apply_components() {
  log "Applying Flux controllers"
  kustomize build flux | kubectl apply -f -
}

apply_age_secret() {
  if kubectl get secret sops-age -n flux-system >/dev/null 2>&1; then
    log "SOPS age secret present"
    return
  fi

  if [[ -z "${SOPS_AGE_KEY_FILE:-}" ]]; then
    cat <<'MSG'
ERROR: The SOPS age identity secret is missing.
Provide the private key via SOPS_AGE_KEY_FILE=/path/to/key.txt before rerunning
this script. Use `age-keygen -o key.txt` to create one and copy the contents to
1Password or your preferred secret manager.
MSG
    exit 1
  fi

  log "Creating SOPS age secret"
  kubectl -n flux-system create secret generic sops-age \
    --from-file=age.agekey="${SOPS_AGE_KEY_FILE}"
}

bootstrap_sync() {
  if flux get kustomization flux-system >/dev/null 2>&1; then
    log "Flux sync already configured"
  else
    log "Bootstrapping Flux sync manifests"
    flux create source git flux-system \
      --url="${REPO_URL}" \
      --branch="${BRANCH}" \
      --interval=1m \
      --namespace=flux-system \
      --export | kubectl apply -f -

    flux create kustomization flux-system \
      --source=flux-system \
      --path="${CLUSTER_PATH}" \
      --prune=true \
      --interval=10m \
      --decryption-provider=sops \
      --decryption-secret=sops-age \
      --namespace=flux-system \
      --export | kubectl apply -f -
  fi
}

log "Starting Flux bootstrap"
ensure_namespace
apply_components
apply_age_secret
bootstrap_sync
log "Bootstrap complete"
