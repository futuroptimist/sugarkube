#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

if ! command -v just >/dev/null 2>&1; then
    echo "just is required for this test" >&2
    exit 1
fi

dry_run_command="$(
    just -n helm-oci-install \
        release=dspace namespace=dspace \
        chart=oci://ghcr.io/democratizedspace/charts/dspace \
        values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml \
        version_file=docs/apps/dspace.version \
        default_tag=v3-latest 2>&1
)"

tmp_bin="$(mktemp -d)"
trap 'rm -rf "${tmp_bin}"' EXIT

cat <<'EOF' >"${tmp_bin}/helm"
#!/usr/bin/env bash
printf '%s\n' "$@" >"${TMP_HELM_OUTPUT}"
EOF
chmod +x "${tmp_bin}/helm"

export TMP_HELM_OUTPUT="${tmp_bin}/helm_args.txt"
PATH="${tmp_bin}:${PATH}"

bash -c "${dry_run_command}"

helm_output="$(cat "${TMP_HELM_OUTPUT}")"

if [[ "${helm_output}" != *"oci://ghcr.io/democratizedspace/charts/dspace"* ]]; then
    echo "Expected chart reference missing from generated Helm invocation" >&2
    echo "Output was: ${helm_output}" >&2
    exit 1
fi

if [[ "${helm_output}" == *"chart=oci://"* ]] || [[ "${helm_output}" == *"chart=chart=oci://"* ]]; then
    echo "Helm invocation still contains a chart= prefix" >&2
    echo "Output was: ${helm_output}" >&2
    exit 1
fi

echo "helm-oci-install recipe renders chart argument correctly"
