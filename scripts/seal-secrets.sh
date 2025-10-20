#!/usr/bin/env bash
set -euo pipefail

# seal-secrets.sh rewraps SOPS-encrypted manifests for a specific environment.

if ! command -v sops >/dev/null 2>&1; then
  echo "sops binary is required to reseal secrets." >&2
  exit 1
fi

ENVIRONMENT="${1:-}"
if [[ -z "${ENVIRONMENT}" ]]; then
  echo "usage: $0 <environment>" >&2
  exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
SECRET_DIR="${REPO_ROOT}/clusters/${ENVIRONMENT}/secrets"

if [[ ! -d "${SECRET_DIR}" ]]; then
  echo "environment '${ENVIRONMENT}' does not have a secrets directory" >&2
  exit 1
fi

shopt -s nullglob
for secret in "${SECRET_DIR}"/*.enc.yaml; do
  echo ":: Updating recipients for ${secret##${REPO_ROOT}/}" >&2
  sops updatekeys "${secret}"
done
shopt -u nullglob

echo "Secrets resealed for environment '${ENVIRONMENT}'."
