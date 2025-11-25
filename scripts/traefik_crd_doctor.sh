#!/usr/bin/env bash
set -Eeuo pipefail

namespace="kube-system"
apply_mode="${TRAEFIK_CRD_DOCTOR_APPLY:-0}"

usage() {
  cat <<'USAGE'
Usage: traefik_crd_doctor.sh [--namespace <ns>] [--apply]

By default this script is read-only and only prints suggested kubectl commands.
Set --apply to execute the delete commands after an interactive confirmation.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --namespace|-n)
      namespace="$2"
      shift 2
      ;;
    --apply)
      apply_mode="1"
      shift 1
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

crd_lib="$(dirname "$0")/lib/traefik_crd.sh"
if [ -f "${crd_lib}" ]; then
  # shellcheck disable=SC1090
  source "${crd_lib}"
else
  echo "ERROR: traefik CRD helper library not found at ${crd_lib}" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: 'jq' is required for CRD inspection." >&2
  exit 1
fi

mapfile -t crd_state_lines < <(traefik_crd_collect_state "${namespace}")

problematic_crds=()
missing_crds=()

for line in "${crd_state_lines[@]}"; do
  IFS='|' read -r crd status managed rel_name rel_ns <<<"${line}"
  case "${status}" in
    healthy)
      ;;
    missing)
      missing_crds+=("${crd}")
      ;;
    *)
      problematic_crds+=("${crd}")
      ;;
  esac

done

echo "Traefik Gateway API CRD doctor (namespace: ${namespace})"
echo "--------------------------------------------------------"

for line in "${crd_state_lines[@]}"; do
  IFS='|' read -r crd status managed rel_name rel_ns <<<"${line}"
  case "${status}" in
    healthy)
      printf '✅ %s: owned by release %s in namespace %s (OK)\n' \
        "${crd}" "${rel_name:-<unknown>}" "${rel_ns:-<unknown>}"
      ;;
    missing)
      printf '⚠️  %s: missing (will be created by Traefik CRD chart)\n' "${crd}"
      ;;
    *)
      printf '⚠️  %s: exists but managed-by=%s, release-name=%s, release-namespace=%s (NOT a Traefik release in %s)\n' \
        "${crd}" "${managed:-<unset>}" "${rel_name:-<unset>}" "${rel_ns:-<unset>}" "${namespace}"
      ;;
  esac

done

if [ "${#problematic_crds[@]}" -eq 0 ]; then
  echo
  echo "No problematic Gateway API CRDs detected."
  if [ "${#missing_crds[@]}" -eq "${#GATEWAY_API_CRDS[@]}" ]; then
    echo "All expected CRDs are missing, so the Traefik CRD chart can create them."
  else
    echo "Existing CRDs are already owned by Traefik Helm releases."
  fi
  exit 0
fi

echo
echo "Detected problematic CRDs that block Traefik's CRD chart:"
printf '  %s\n' "${problematic_crds[@]}"

echo
echo "Suggested fix commands (dry-run only):"
echo "1) Delete and recreate (recommended for fresh clusters):"
printf '   kubectl delete crd %s\n' "${problematic_crds[*]}"
echo

echo "2) Patch for Helm adoption (advanced):"
for crd in "${problematic_crds[@]}"; do
  printf '   kubectl label crd %s app.kubernetes.io/managed-by=Helm --overwrite\n' "${crd}"
  printf '   kubectl annotate crd %s \\\n     meta.helm.sh/release-name=traefik-crd \\\n     meta.helm.sh/release-namespace=%s \\\n     --overwrite\n' "${crd}" "${namespace}"
done

action_taken=0
if [ "${apply_mode}" = "1" ]; then
  echo
  cat <<'WARNING'
WARNING: traefik-crd-doctor apply mode will make **destructive changes** to cluster-wide CRDs.
This can break other workloads if they depend on Gateway API resources.
Only use this mode on a fresh homelab cluster where you understand the consequences.
WARNING

  echo "Planned kubectl delete command:"
  printf '  kubectl delete crd %s\n' "${problematic_crds[*]}"
  echo
  read -r -p "Proceed with these changes? [y/N]: " confirm
  if [ "${confirm}" != "y" ] && [ "${confirm}" != "Y" ]; then
    echo "Aborting without making changes."
    exit 1
  fi

  echo "Executing kubectl delete for problematic CRDs..."
  if ! kubectl delete crd "${problematic_crds[@]}"; then
    echo "ERROR: kubectl delete failed." >&2
    exit 1
  fi
  action_taken=1
fi

after_lines=()
if [ "${action_taken}" -eq 1 ]; then
  echo
  echo "Re-checking CRD state after apply..."
  mapfile -t after_lines < <(traefik_crd_collect_state "${namespace}")
else
  after_lines=("${crd_state_lines[@]}")
fi

problematic_after=0
for line in "${after_lines[@]}"; do
  IFS='|' read -r _ status _ _ _ <<<"${line}"
  if [ "${status}" = "problematic" ]; then
    problematic_after=1
    break
  fi

done

if [ "${problematic_after}" -eq 0 ]; then
  echo "CRD state is now clean."
  exit 0
fi

exit 1
