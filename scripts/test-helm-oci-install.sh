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
fake_registry="oci://registry.test.local/charts/dspace"

cat >"${tmp_bin}/helm" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

echo "helm $*" | tee -a "${HELM_TEST_LOG:-/dev/null}"
SH
chmod +x "${tmp_bin}/helm"

cat >"${tmp_bin}/kubectl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

echo "kubectl $*" >> "${KUBECTL_TEST_LOG:-/dev/null}"

if [[ "${1:-}" == "-n" && "${3:-}" == "get" && "${4:-}" == "deploy" ]]; then
    printf 'dspace\n'
    exit 0
fi

if [[ "${1:-}" == "-n" && "${3:-}" == "rollout" && "${4:-}" == "status" ]]; then
    exit 0
fi

exit 0
SH
chmod +x "${tmp_bin}/kubectl"

command_output="$(
    PATH="${tmp_bin}:${PATH}" HELM_TEST_LOG="${helm_log}" \
        KUBECTL_TEST_LOG="${kubectl_log}" \
        just helm-oci-install \
        release=dspace namespace=dspace \
        chart="${fake_registry}" \
        values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml \
        version_file=docs/apps/dspace.version \
        default_tag=v3-latest
)"

if ! grep -q "${fake_registry}" <<<"${command_output}"; then
    printf 'Expected chart argument missing from generated output.\nOutput:\n%s\n' "${command_output}" >&2
    exit 1
fi

if grep -Eq "chart=oci://|chart=chart=oci://" <<<"${command_output}"; then
    printf 'Found unexpected chart= prefix in generated output.\nOutput:\n%s\n' "${command_output}" >&2
    exit 1
fi

if ! grep -q "${fake_registry}" "${helm_log}"; then
    printf 'Stubbed helm did not receive expected chart argument.\nLog:\n%s\n' "$(cat "${helm_log}" 2>/dev/null || true)" >&2
    exit 1
fi

if grep -Eq "chart=oci://|chart=chart=oci://" "${helm_log}"; then
    printf 'Stubbed helm received chart argument with unexpected prefix.\nLog:\n%s\n' "$(cat "${helm_log}" 2>/dev/null || true)" >&2
    exit 1
fi

if ! grep -q "Waiting for Helm release 'dspace' rollout(s) to complete" <<<"${command_output}"; then
    printf 'Expected rollout feedback missing from output.\nOutput:\n%s\n' "${command_output}" >&2
    exit 1
fi

if ! grep -q "kubectl -n dspace rollout status deploy/dspace --timeout 180s" "${kubectl_log}"; then
    printf 'Expected rollout status check not observed.\nLog:\n%s\n' "$(cat "${kubectl_log}" 2>/dev/null || true)" >&2
    exit 1
fi

printf 'helm-oci-install emits normalized OCI chart argument and rollout feedback.\n'
