#!/usr/bin/env bash
# shellcheck shell=bash

if [ -n "${SUGARKUBE_TRAEFIK_GATEWAY_CRD_LIB_SOURCED:-}" ]; then
  return 0
fi
SUGARKUBE_TRAEFIK_GATEWAY_CRD_LIB_SOURCED=1

traefik_gateway_crd::names() {
  cat <<'NAMES'
backendtlspolicies.gateway.networking.k8s.io
gatewayclasses.gateway.networking.k8s.io
gateways.gateway.networking.k8s.io
grpcroutes.gateway.networking.k8s.io
httproutes.gateway.networking.k8s.io
referencegrants.gateway.networking.k8s.io
NAMES
}

traefik_gateway_crd::detect() {
  local kubectl_bin
  kubectl_bin="${KUBECTL_BIN:-kubectl}"

  GATEWAY_CRD_PRESENT=()
  GATEWAY_CRD_MISSING=()
  GATEWAY_CRD_OK=()
  GATEWAY_CRD_PROBLEM=()
  GATEWAY_CRD_RELEASES=()
  declare -gA GATEWAY_CRD_MANAGED_BY
  declare -gA GATEWAY_CRD_RELEASE_NAME
  declare -gA GATEWAY_CRD_RELEASE_NAMESPACE

  for crd in $(traefik_gateway_crd::names); do
    if "${kubectl_bin}" get crd "${crd}" >/dev/null 2>&1; then
      GATEWAY_CRD_PRESENT+=("${crd}")
      GATEWAY_CRD_MANAGED_BY["${crd}"]=$("${kubectl_bin}" get crd "${crd}" \
        -o jsonpath='{.metadata.labels.app\.kubernetes\.io/managed-by}' 2>/dev/null || true)
      GATEWAY_CRD_RELEASE_NAME["${crd}"]=$("${kubectl_bin}" get crd "${crd}" \
        -o jsonpath='{.metadata.annotations.meta\.helm\.sh/release-name}' 2>/dev/null || true)
      GATEWAY_CRD_RELEASE_NAMESPACE["${crd}"]=$("${kubectl_bin}" get crd "${crd}" \
        -o jsonpath='{.metadata.annotations.meta\.helm\.sh/release-namespace}' 2>/dev/null || true)

      if [ "${GATEWAY_CRD_MANAGED_BY[${crd}]:-}" = "Helm" ] && \
        { [ "${GATEWAY_CRD_RELEASE_NAME[${crd}]:-}" = "traefik" ] || \
          [ "${GATEWAY_CRD_RELEASE_NAME[${crd}]:-}" = "traefik-crd" ]; } && \
        [ "${GATEWAY_CRD_RELEASE_NAMESPACE[${crd}]:-}" = "kube-system" ]; then
        GATEWAY_CRD_OK+=("${crd}")
        GATEWAY_CRD_RELEASES+=("${GATEWAY_CRD_RELEASE_NAME[${crd}]:-}")
      else
        GATEWAY_CRD_PROBLEM+=("${crd}")
      fi
    else
      GATEWAY_CRD_MISSING+=("${crd}")
    fi
  done
}
