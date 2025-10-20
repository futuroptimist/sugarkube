#!/usr/bin/env bash
set -euo pipefail

# flux-bootstrap.sh bootstraps a k3s cluster with Flux and SOPS support.
# The script is idempotent: rerunning it updates Flux components and syncs Git state.

REPO_ROOT="$(git rev-parse --show-toplevel)"
CLUSTER_ENV="${1:-dev}"

if ! command -v flux >/dev/null 2>&1; then
  echo "flux CLI is required. Install from https://fluxcd.io/flux/ before running." >&2
  exit 1
fi

if ! command -v sops >/dev/null 2>&1; then
  echo "sops is required to decrypt secrets." >&2
  exit 1
fi

KUBECONFIG_PATH="${KUBECONFIG:-$HOME/.kube/config}"
if [ ! -f "$KUBECONFIG_PATH" ]; then
  echo "kubeconfig not found at $KUBECONFIG_PATH" >&2
  exit 1
fi

echo ":: Ensuring flux-system namespace exists"
kubectl get namespace flux-system >/dev/null 2>&1 || kubectl create namespace flux-system

echo ":: Applying Flux components"
flux install --export >"${REPO_ROOT}/flux/tmp-install.yaml"
kubectl apply -f "${REPO_ROOT}/flux/tmp-install.yaml"
rm -f "${REPO_ROOT}/flux/tmp-install.yaml"

echo ":: Applying repository and kustomization manifests"
KUSTOMIZE_ENV_PATH="${REPO_ROOT}/clusters/${CLUSTER_ENV}"
if [ ! -d "$KUSTOMIZE_ENV_PATH" ]; then
  echo "environment '${CLUSTER_ENV}' not found under clusters/." >&2
  exit 1
fi

export CLUSTER_ENV
TMP_SYNC="$(mktemp)"
trap 'rm -f "${TMP_SYNC}"' EXIT
envsubst <"${REPO_ROOT}/flux/gotk-sync.yaml" >"${TMP_SYNC}"

kubectl apply -f "${TMP_SYNC}" \
  --server-side --force-conflicts
kubectl apply -f "${REPO_ROOT}/flux/gotk-components.yaml" \
  --server-side --force-conflicts

if kubectl get secret -n flux-system sops-age >/dev/null 2>&1; then
  echo ":: sops-age secret already present"
else
  echo ":: Creating placeholder sops-age secret"
  kubectl create secret generic sops-age \
    --namespace flux-system \
    --from-literal=age.agekey="AGE-SECRET-KEY-PLACEHOLDER" \
    --dry-run=client -o yaml | kubectl apply -f -
fi

echo ":: Labeling flux-system namespace for garbage collection safety"
kubectl label namespace flux-system toolkit.fluxcd.io/tenant=platform --overwrite

echo ":: Verifying decryption configuration"
flux get sources git flux-system || true
flux reconcile source git flux-system --with-source

if flux get kustomizations platform >/dev/null 2>&1; then
  flux reconcile kustomization platform --with-source
else
  echo "waiting for Flux to create kustomization" >&2
fi

echo "Bootstrap complete for environment '${CLUSTER_ENV}'."
