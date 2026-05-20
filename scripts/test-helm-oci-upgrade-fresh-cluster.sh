#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

if ! command -v just >/dev/null 2>&1; then
    echo "The 'just' command is required to run this test." >&2
    exit 1
fi

tmp_bin="$(mktemp -d)"
trap 'rm -rf "${tmp_bin}"' EXIT
helm_log="${tmp_bin}/helm.log"
kubectl_log="${tmp_bin}/kubectl.log"

cat >"${tmp_bin}/helm" <<'EOS'
#!/usr/bin/env bash
set -euo pipefail

echo "helm $*" >> "${HELM_TEST_LOG:-/dev/null}"

if [ "${1:-}" = "-n" ] && [ "${2:-}" = "dspace" ] && [ "${3:-}" = "status" ] && [ "${4:-}" = "missing" ]; then
    echo 'Error: release: not found' >&2
    exit 1
fi

if [ "${1:-}" = "-n" ] && [ "${2:-}" = "dspace" ] && [ "${3:-}" = "status" ] && [ "${4:-}" = "dspace" ]; then
    echo '{"info":{"status":"deployed"}}'
    exit 0
fi

if [ "${1:-}" = "upgrade" ]; then
    exit 0
fi

exit 0
EOS
chmod +x "${tmp_bin}/helm"

cat >"${tmp_bin}/kubectl" <<'EOS'
#!/usr/bin/env bash
set -euo pipefail

echo "kubectl $*" >> "${KUBECTL_TEST_LOG:-/dev/null}"
if [ "${1:-}" = "-n" ] && [ "${2:-}" = "dspace" ] && [ "${3:-}" = "get" ] && [ "${4:-}" = "deploy,statefulset,daemonset" ] && [ "${5:-}" = "-l" ] && [ "${6:-}" = "app.kubernetes.io/instance=dspace" ]; then
    echo "deployment.apps/dspace"
    exit 0
fi
if [ "${1:-}" = "-n" ] && [ "${2:-}" = "dspace" ] && [ "${3:-}" = "rollout" ] && [ "${4:-}" = "status" ]; then
    exit 0
fi
exit 0
EOS
chmod +x "${tmp_bin}/kubectl"

set +e
fresh_output="$({
    PATH="${tmp_bin}:${PATH}" HELM_TEST_LOG="${helm_log}" KUBECTL_TEST_LOG="${kubectl_log}" \
        KUBECONFIG="${tmp_bin}/kubeconfig" \
        just helm-oci-upgrade release=missing namespace=dspace chart=oci://registry.test/charts/dspace 2>&1
}; echo "__CODE:$?")"
set -e

if ! grep -q "__CODE:1" <<<"${fresh_output}"; then
    printf 'Expected fresh-cluster upgrade path to fail. Output:\n%s\n' "${fresh_output}" >&2
    exit 1
fi

if ! grep -q "helm-oci-upgrade requires an existing deployed release" <<<"${fresh_output}"; then
    printf 'Expected actionable fresh-cluster message not found. Output:\n%s\n' "${fresh_output}" >&2
    exit 1
fi

if ! grep -q "just helm-oci-install" <<<"${fresh_output}"; then
    printf 'Expected install guidance missing. Output:\n%s\n' "${fresh_output}" >&2
    exit 1
fi

if grep -q "helm upgrade missing" "${helm_log}"; then
    printf 'Upgrade command should not run for missing release. Log:\n%s\n' "$(cat "${helm_log}" 2>/dev/null || true)" >&2
    exit 1
fi

existing_output="$({
    PATH="${tmp_bin}:${PATH}" HELM_TEST_LOG="${helm_log}" KUBECTL_TEST_LOG="${kubectl_log}" \
        KUBECONFIG="${tmp_bin}/kubeconfig" \
        just helm-oci-upgrade release=dspace namespace=dspace chart=oci://registry.test/charts/dspace
} 2>&1)"

if ! grep -q "helm upgrade dspace oci://registry.test/charts/dspace --namespace dspace --reuse-values" <<<"${existing_output}"; then
    printf 'Expected upgrade command output missing. Output:\n%s\n' "${existing_output}" >&2
    exit 1
fi

install_output="$({
    PATH="${tmp_bin}:${PATH}" HELM_TEST_LOG="${helm_log}" KUBECTL_TEST_LOG="${kubectl_log}" \
        KUBECONFIG="${tmp_bin}/kubeconfig" \
        just helm-oci-install release=release=dspace namespace=namespace=dspace chart=chart=oci://registry.test/charts/dspace
} 2>&1)"

if ! grep -q -- "--install --create-namespace" <<<"${install_output}"; then
    printf 'Expected install flags missing from install path. Output:\n%s\n' "${install_output}" >&2
    exit 1
fi

if ! grep -q "helm -n dspace status dspace -o json" "${helm_log}"; then
    printf 'Expected prefixed argument normalization to feed status check. Log:\n%s\n' "$(cat "${helm_log}" 2>/dev/null || true)" >&2
    exit 1
fi

printf 'helm-oci-upgrade fresh-cluster guardrails and install/upgrade paths validated.\n'
