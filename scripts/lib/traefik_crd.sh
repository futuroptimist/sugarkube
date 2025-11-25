#!/usr/bin/env bash
set -Eeuo pipefail

# Shared helpers for inspecting Traefik Gateway API CRDs and their Helm ownership metadata.

# Gateway API CRDs managed by the Traefik chart.
GATEWAY_API_CRDS=(
  backendtlspolicies.gateway.networking.k8s.io
  gatewayclasses.gateway.networking.k8s.io
  gateways.gateway.networking.k8s.io
  grpcroutes.gateway.networking.k8s.io
  httproutes.gateway.networking.k8s.io
  referencegrants.gateway.networking.k8s.io
)

TRAEFIK_HELM_RELEASES=(traefik traefik-crd)

traefik_crd_collect_state() {
  local namespace="${1:-kube-system}"

  local crd
  for crd in "${GATEWAY_API_CRDS[@]}"; do
    local crd_json
    if ! crd_json=$(kubectl get "crd/${crd}" -o json 2>/dev/null); then
      printf '%s|missing|||\n' "${crd}"
      continue
    fi

    local managed_by
    local release_name
    local release_namespace

    managed_by=$(printf '%s' "${crd_json}" |
      jq -r '.metadata.labels["app.kubernetes.io/managed-by"] // ""')
    release_name=$(printf '%s' "${crd_json}" |
      jq -r '.metadata.annotations["meta.helm.sh/release-name"] // ""')
    release_namespace=$(printf '%s' "${crd_json}" |
      jq -r '.metadata.annotations["meta.helm.sh/release-namespace"] // ""')

    local normalized_release=""
    local accepted
    for accepted in "${TRAEFIK_HELM_RELEASES[@]}"; do
      if [ "${release_name}" = "${accepted}" ]; then
        normalized_release="${release_name}"
        break
      fi
    done

    local status="problematic"
    if [ "${managed_by}" = "Helm" ] && \
      [ -n "${normalized_release}" ] && \
      [ "${release_namespace}" = "${namespace}" ]; then
      status="healthy"
    fi

    printf '%s|%s|%s|%s|%s\n' \
      "${crd}" "${status}" "${managed_by}" "${release_name}" "${release_namespace}"
  done
}
