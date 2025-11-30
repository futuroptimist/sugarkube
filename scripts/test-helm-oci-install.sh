#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

if ! command -v just >/dev/null 2>&1; then
    echo "The 'just' command is required to run this test." >&2
    exit 1
fi

tmp_bin="$(mktemp -d)"
helm_log="${tmp_bin}/helm.log"

cat >"${tmp_bin}/helm" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

echo "helm $*" | tee -a "${HELM_TEST_LOG:-/dev/null}"
SH
chmod +x "${tmp_bin}/helm"

command_output="$(
    PATH="${tmp_bin}:${PATH}" HELM_TEST_LOG="${helm_log}" \
        just helm-oci-install \
        release=dspace namespace=dspace \
        chart=oci://ghcr.io/democratizedspace/charts/dspace \
        values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml \
        version_file=docs/apps/dspace.version \
        default_tag=v3-latest
)"

if ! grep -q "oci://ghcr.io/democratizedspace/charts/dspace" <<<"${command_output}"; then
    printf 'Expected chart argument missing from generated output.\nOutput:\n%s\n' "${command_output}" >&2
    exit 1
fi

if grep -Eq "chart=oci://|chart=chart=oci://" <<<"${command_output}"; then
    printf 'Found unexpected chart= prefix in generated output.\nOutput:\n%s\n' "${command_output}" >&2
    exit 1
fi

if ! grep -q "oci://ghcr.io/democratizedspace/charts/dspace" "${helm_log}"; then
    printf 'Stubbed helm did not receive expected chart argument.\nLog:\n%s\n' "$(cat "${helm_log}" 2>/dev/null || true)" >&2
    exit 1
fi

if grep -Eq "chart=oci://|chart=chart=oci://" "${helm_log}"; then
    printf 'Stubbed helm received chart argument with unexpected prefix.\nLog:\n%s\n' "$(cat "${helm_log}" 2>/dev/null || true)" >&2
    exit 1
fi

printf 'helm-oci-install emits normalized chart argument.\n'
