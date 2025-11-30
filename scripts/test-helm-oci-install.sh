#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

release_arg="release=dspace"
namespace_arg="namespace=dspace"
chart_arg="chart=oci://ghcr.io/democratizedspace/charts/dspace"
values_arg="values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml"
version_file_arg="version_file=docs/apps/dspace.version"
default_tag_arg="default_tag=v3-latest"

cd "${repo_root}"

dry_run_output="$(just -n helm-oci-install \
    "${release_arg}" "${namespace_arg}" "${chart_arg}" "${values_arg}" \
    "${version_file_arg}" "${default_tag_arg}" 2>&1)"

if ! grep -q "oci://ghcr.io/democratizedspace/charts/dspace" <<<"${dry_run_output}"; then
    echo "Dry-run output did not contain the expected chart string." >&2
    exit 1
fi

if grep -q "chart=chart=oci://" <<<"${dry_run_output}"; then
    echo "Dry-run output still contains a double chart= prefix." >&2
    exit 1
fi

sandbox="$(mktemp -d)"
trap 'rm -rf "${sandbox}"' EXIT

cat >"${sandbox}/helm" <<'STUB'
#!/usr/bin/env bash
echo "HELM_ARGS:$*"
STUB
chmod +x "${sandbox}/helm"

helm_output="$(PATH="${sandbox}:${PATH}" just _helm-oci-deploy \
    "${release_arg}" "${namespace_arg}" "${chart_arg}" "${values_arg}" \
    "" "" "${version_file_arg}" "" "${default_tag_arg}" \
    allow_install=true reuse_values=false)"

helm_line="$(grep -F "HELM_ARGS:" <<<"${helm_output}")"

if [[ -z "${helm_line}" ]]; then
    echo "Stub helm did not run; output was:\n${helm_output}" >&2
    exit 1
fi

if ! grep -q "oci://ghcr.io/democratizedspace/charts/dspace" <<<"${helm_line}"; then
    echo "Stub helm invocation did not include the chart argument: ${helm_line}" >&2
    exit 1
fi

if grep -q "chart=oci://" <<<"${helm_line}"; then
    echo "Stub helm invocation still contains a chart= prefix: ${helm_line}" >&2
    exit 1
fi

echo "helm-oci-install dry-run and execution plumbing look correct."
