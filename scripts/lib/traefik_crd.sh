#!/usr/bin/env bash
# shellcheck shell=bash

# Guard against multiple sourcing.
if [ -n "${SUGARKUBE_TRAEFIK_CRD_LIB_SOURCED:-}" ]; then
  return 0
fi
SUGARKUBE_TRAEFIK_CRD_LIB_SOURCED=1

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
TRAEFIK_CRD_UNMANAGED=()
TRAEFIK_CRD_PROBLEMS=()
TRAEFIK_CRD_PROBLEM_DETAILS=()
TRAEFIK_CRD_RELEASE_NAMES=()

traefik_crd::reset_state() {
  TRAEFIK_CRD_PRESENT=()
  TRAEFIK_CRD_MISSING=()
  TRAEFIK_CRD_OK=()
  TRAEFIK_CRD_UNMANAGED=()
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

    if [ -z "${managed_by}" ] && [ -z "${rel_name}" ] && [ -z "${rel_namespace}" ]; then
      TRAEFIK_CRD_UNMANAGED+=("${crd}")
      continue
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
  local apply_mode="${2:-0}"

  local has_problems=false
  if [ "${#TRAEFIK_CRD_PROBLEMS[@]}" -gt 0 ]; then
    has_problems=true
  fi

  echo "=== Gateway API CRD ownership check (expected release namespace: ${namespace}) ==="
  local crd
  for crd in "${TRAEFIK_GATEWAY_CRDS[@]}"; do
    if traefik_crd::array_contains "${crd}" TRAEFIK_CRD_MISSING[@]; then
      if [ "${has_problems}" = false ]; then
        printf '✅ %s: missing (will be created by the Traefik chart if enabled)\n' "${crd}"
      else
        printf '⚠️  %s: missing or not present\n' "${crd}"
      fi
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

    if traefik_crd::array_contains "${crd}" TRAEFIK_CRD_UNMANAGED[@]; then
      printf '✅ %s: present without Helm ownership metadata (will adopt into Traefik release)\n' "${crd}"
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

  echo

  local has_present=false
  if [ "${#TRAEFIK_CRD_PRESENT[@]}" -gt 0 ]; then
    has_present=true
  fi

  local has_unmanaged=false
  if [ "${#TRAEFIK_CRD_UNMANAGED[@]}" -gt 0 ]; then
    has_unmanaged=true
  fi

  if [ "${has_problems}" = true ]; then
    echo "Detected problematic Gateway API CRDs that block clean Traefik ownership. See the recommended actions below."
  elif [ "${has_present}" = false ]; then
    echo "No problematic Gateway API CRDs detected. All expected CRDs are missing; the Traefik chart can create them when installed."
  elif [ "${has_unmanaged}" = true ]; then
    echo "No problematic Gateway API CRDs detected. Existing CRDs are present without Helm ownership metadata; Traefik can adopt them into its release."
    echo "Traefik will add Helm labels/annotations and take ownership of these CRDs during install."
  else
    echo "No problematic Gateway API CRDs detected. Existing CRDs are already owned by Traefik Helm releases."
  fi

  if [ "${apply_mode}" = "1" ]; then
    return 0
  fi

  if [ "${has_problems}" = false ] && [ "${has_present}" = false ]; then
    echo "Next step: run 'just traefik-install' to install Traefik and let it create the CRDs."
  elif [ "${has_problems}" = false ]; then
    echo "Next step: you can safely run 'just traefik-install' (or re-run it) if you want to upgrade Traefik."
  fi
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
  1) Delete and let Traefik recreate (safest for fresh clusters):
     kubectl delete crd ${joined}

  2) Patch to mark Helm ownership (advanced; for preserving existing Gateway API workloads):
     kubectl label crd <name> app.kubernetes.io/managed-by=Helm --overwrite
     kubectl annotate crd <name> \
       meta.helm.sh/release-name=traefik \
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

  echo "Running: kubectl delete crd ${TRAEFIK_CRD_PROBLEMS[@]}"
  kubectl delete crd "${TRAEFIK_CRD_PROBLEMS[@]}"
}

traefik_crd::adopt_unmanaged() {
  if [ "${#TRAEFIK_CRD_UNMANAGED[@]}" -eq 0 ]; then
    return 0
  fi

  local namespace="${1:-kube-system}"
  local release_name="${2:-traefik}"

  echo "Adopting unmanaged Gateway API CRDs into Helm release '${release_name}' in namespace '${namespace}'..."
  local crd
  for crd in "${TRAEFIK_CRD_UNMANAGED[@]}"; do
    if ! kubectl label crd "${crd}" app.kubernetes.io/managed-by=Helm --overwrite; then
      echo "WARNING: Failed to label ${crd}; ownership metadata may remain unset." >&2
      continue
    fi
    if ! kubectl annotate crd "${crd}" \
      "meta.helm.sh/release-name=${release_name}" \
      "meta.helm.sh/release-namespace=${namespace}" --overwrite; then
      echo "WARNING: Failed to annotate ${crd}; ownership metadata may remain unset." >&2
    fi
  done
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
