#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KUBECONFIG_LIB="${SCRIPT_DIR}/lib/kubeconfig.sh"

if [ -f "${KUBECONFIG_LIB}" ]; then
  # shellcheck source=lib/kubeconfig.sh disable=SC1091
  . "${KUBECONFIG_LIB}"
else
  echo "kubeconfig library not found at ${KUBECONFIG_LIB}; kubeconfig setup skipped" >&2
  exit 1
fi

kubeconfig::ensure_user_kubeconfig
