#!/usr/bin/env bash
set -euo pipefail

# Bootstrap Flux into a new or rebuilt k3s control plane. The script is idempotent and safe
# to re-run; it only applies manifests and secrets that live in this repository.
#
# Requirements:
#   - flux v2.3.0+
#   - kubectl with access to the target cluster
#   - sops + age private key matching flux/secrets/sops-age.enc.yaml
#
# Usage:
#   scripts/flux-bootstrap.sh <environment>
#
# Example:
#   scripts/flux-bootstrap.sh dev
#
ENVIRONMENT="${1:-}"
if [[ -z "${ENVIRONMENT}" ]]; then
  echo "Usage: $0 <environment>" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if ! command -v flux >/dev/null 2>&1; then
  echo "flux CLI is required" >&2
  exit 2
fi

if ! command -v sops >/dev/null 2>&1; then
  echo "sops is required to decrypt secrets" >&2
  exit 3
fi

export SOPS_AGE_KEY_FILE="${REPO_ROOT}/.age.key"
if [[ ! -f "${SOPS_AGE_KEY_FILE}" ]]; then
  echo "Copy your age private key to ${SOPS_AGE_KEY_FILE} before running." >&2
  exit 4
fi

kubectl apply -k "${REPO_ROOT}/flux"

GIT_URL="$(git -C "${REPO_ROOT}" remote get-url origin 2>/dev/null || echo "")"
if [[ -n "${GIT_URL}" ]]; then
  flux create source git sugarkube \
    --namespace flux-system \
    --url "${GIT_URL}" \
    --branch main \
    --interval 1m \
    --export | kubectl apply -f -
fi

flux create kustomization platform \
  --namespace flux-system \
  --source GitRepository/sugarkube \
  --path "./clusters/${ENVIRONMENT}" \
  --prune true \
  --interval 5m \
  --decryption-provider sops \
  --decryption-secret sops-age \
  --export | kubectl apply -f -

kubectl -n flux-system rollout status deploy/source-controller --timeout=2m || true
kubectl -n flux-system rollout status deploy/kustomize-controller --timeout=2m || true
kubectl -n flux-system rollout status deploy/helm-controller --timeout=2m || true
