#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

TRAEFIK_GATEWAY_CRDS=(
  backendtlspolicies.gateway.networking.k8s.io
  gatewayclasses.gateway.networking.k8s.io
  gateways.gateway.networking.k8s.io
  grpcroutes.gateway.networking.k8s.io
  httproutes.gateway.networking.k8s.io
  referencegrants.gateway.networking.k8s.io
)

TRAEFIK_EXPECTED_RELEASES=(traefik traefik-crd)

TRAEFIK_CRD_PRESENT=()
TRAEFIK_CRD_MISSING=()
TRAEFIK_CRD_OK=()
TRAEFIK_CRD_PROBLEMS=()
TRAEFIK_CRD_PROBLEM_DETAILS=()
TRAEFIK_CRD_RELEASE_NAMES=()

traefik_crd::reset_state() {
  TRAEFIK_CRD_PRESENT=()
  TRAEFIK_CRD_MISSING=()
  TRAEFIK_CRD_OK=()
  TRAEFIK_CRD_PROBLEMS=()
  TRAEFIK_CRD_PROBLEM_DETAILS=()
  TRAEFIK_CRD_RELEASE_NAMES=()
}

traefik_crd::gateway_crds() {
  printf '%s\n' "${TRAEFIK_GATEWAY_CRDS[@]}"
}

traefik_crd::is_expected_release() {
  local candidate="$1"
  local rel
  for rel in "${TRAEFIK_EXPECTED_RELEASES[@]}"; do
    if [ "${candidate}" = "${rel}" ]; then
      return 0
    fi
  done
  return 1
}

traefik_crd::dedupe_release_names() {
  if [ "${#TRAEFIK_CRD_RELEASE_NAMES[@]}" -eq 0 ]; then
    return 0
  fi

  printf '%s\n' "${TRAEFIK_CRD_RELEASE_NAMES[@]}" \
    | sed '/^$/d' \
    | sort -u \
    | tr '\n' ' '
}

traefik_crd::classify_all() {
  local namespace="${1:-kube-system}"

  traefik_crd::reset_state

  for crd in "${TRAEFIK_GATEWAY_CRDS[@]}"; do
    if ! kubectl get "crd/${crd}" >/dev/null 2>&1; then
      TRAEFIK_CRD_MISSING+=("${crd}")
      continue
    fi

    TRAEFIK_CRD_PRESENT+=("${crd}")

    local managed_by
    local rel_name
    local rel_namespace
    managed_by=$(kubectl get "crd/${crd}" \
      -o jsonpath='{.metadata.labels.app\.kubernetes\.io/managed-by}' 2>/dev/null || echo "")
    rel_name=$(kubectl get "crd/${crd}" \
      -o jsonpath='{.metadata.annotations.meta\.helm\.sh/release-name}' 2>/dev/null || echo "")
    rel_namespace=$(kubectl get "crd/${crd}" \
      -o jsonpath='{.metadata.annotations.meta\.helm\.sh/release-namespace}' 2>/dev/null || echo "")

    if [ -n "${rel_name}" ]; then
      TRAEFIK_CRD_RELEASE_NAMES+=("${rel_name}")
    fi

    if [ "${managed_by}" = "Helm" ] && \
      traefik_crd::is_expected_release "${rel_name}" && \
      [ "${rel_namespace}" = "${namespace}" ]; then
      TRAEFIK_CRD_OK+=("${crd}|${rel_name}|${rel_namespace}")
      continue
    fi

    TRAEFIK_CRD_PROBLEMS+=("${crd}")
    TRAEFIK_CRD_PROBLEM_DETAILS+=(
      "${crd}|${managed_by:-<unset>}|${rel_name:-<unset>}|${rel_namespace:-<unset>}"
    )
  done
}

traefik_crd::print_report() {
  local namespace="${1:-kube-system}"

  echo "=== Gateway API CRD ownership check (expected release namespace: ${namespace}) ==="
  local crd
  for crd in "${TRAEFIK_GATEWAY_CRDS[@]}"; do
    if traefik_crd::array_contains "${crd}" TRAEFIK_CRD_MISSING[@]; then
      printf '⚠️  %s: missing or not present\n' "${crd}"
      continue
    fi

    if traefik_crd::array_contains_prefix "${crd}|" TRAEFIK_CRD_OK[@]; then
      local detail
      detail=$(traefik_crd::lookup_detail "${crd}" TRAEFIK_CRD_OK[@])
      local rel_name rel_namespace
      rel_name=$(cut -d '|' -f 2 <<<"${detail}")
      rel_namespace=$(cut -d '|' -f 3 <<<"${detail}")
      printf '✅ %s: owned by release %s in namespace %s (OK)\n' \
        "${crd}" "${rel_name}" "${rel_namespace}"
      continue
    fi

    local problem
    problem=$(traefik_crd::lookup_detail "${crd}" TRAEFIK_CRD_PROBLEM_DETAILS[@])
    local managed rel_name rel_namespace
    managed=$(cut -d '|' -f 2 <<<"${problem}")
    rel_name=$(cut -d '|' -f 3 <<<"${problem}")
    rel_namespace=$(cut -d '|' -f 4 <<<"${problem}")
    printf '⚠️  %s: managed-by=%s, release-name=%s, release-namespace=%s (expected Traefik Helm in %s)\n' \
      "${crd}" "${managed}" "${rel_name}" "${rel_namespace}" "${namespace}"
  done
}

traefik_crd::print_problem_details() {
  if [ "${#TRAEFIK_CRD_PROBLEM_DETAILS[@]}" -eq 0 ]; then
    return 0
  fi

  echo "Current metadata for problematic CRDs:"
  local entry
  for entry in "${TRAEFIK_CRD_PROBLEM_DETAILS[@]}"; do
    local crd managed rel_name rel_ns
    crd=$(cut -d '|' -f 1 <<<"${entry}")
    managed=$(cut -d '|' -f 2 <<<"${entry}")
    rel_name=$(cut -d '|' -f 3 <<<"${entry}")
    rel_ns=$(cut -d '|' -f 4 <<<"${entry}")
    cat <<CRD_EOF
  - ${crd}
      app.kubernetes.io/managed-by: ${managed}
      meta.helm.sh/release-name: ${rel_name}
      meta.helm.sh/release-namespace: ${rel_ns}
CRD_EOF
  done
}

traefik_crd::print_suggestions() {
  if [ "${#TRAEFIK_CRD_PROBLEMS[@]}" -eq 0 ]; then
    return 0
  fi

  local joined
  joined=$(traefik_crd::join_items TRAEFIK_CRD_PROBLEMS[@])

  cat <<SUGGEST_EOF
Recommended actions:
  1) Delete and let Traefik recreate (fresh clusters):
     kubectl delete crd ${joined}

  2) Patch to mark Helm ownership (advanced):
     kubectl label crd <name> app.kubernetes.io/managed-by=Helm --overwrite
     kubectl annotate crd <name> \
       meta.helm.sh/release-name=traefik-crd \
       meta.helm.sh/release-namespace=kube-system --overwrite
SUGGEST_EOF
}

traefik_crd::print_apply_warning() {
  cat <<WARN_EOF
WARNING: traefik-crd-doctor apply mode will make destructive changes to cluster-wide CRDs.
This can break workloads that depend on Gateway API resources.
Only use this on a fresh homelab cluster if you are sure nothing else depends on these CRDs.
WARN_EOF
}

traefik_crd::apply_delete() {
  if [ "${#TRAEFIK_CRD_PROBLEMS[@]}" -eq 0 ]; then
    return 0
  fi

  echo "Running: kubectl delete crd ${TRAEFIK_CRD_PROBLEMS[*]}"
  kubectl delete crd "${TRAEFIK_CRD_PROBLEMS[@]}"
}

traefik_crd::array_contains() {
  local needle="$1"
  shift
  local array=("${!1}")
  local element
  for element in "${array[@]}"; do
    if [ "${element}" = "${needle}" ]; then
      return 0
    fi
  done
  return 1
}

traefik_crd::array_contains_prefix() {
  local needle_prefix="$1"
  shift
  local array=("${!1}")
  local element
  for element in "${array[@]}"; do
    if [[ "${element}" == "${needle_prefix}"* ]]; then
      return 0
    fi
  done
  return 1
}

traefik_crd::lookup_detail() {
  local needle="$1"
  shift
  local array=("${!1}")
  local element
  for element in "${array[@]}"; do
    if [[ "${element}" == "${needle}|"* ]]; then
      echo "${element}"
      return 0
    fi
  done
  echo ""
}

traefik_crd::join_items() {
  local array=("${!1}")
  local IFS=' '
  echo "${array[*]}"
}
