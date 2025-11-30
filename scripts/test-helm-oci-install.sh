#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

target_chart="oci://ghcr.io/democratizedspace/charts/dspace"
values_arg="docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml"

dry_run_output="$(
    just -n helm-oci-install 2>&1 \
        release=dspace namespace=dspace \
        chart="${target_chart}" \
        values="${values_arg}" \
        version_file=docs/apps/dspace.version \
        default_tag=v3-latest
)"

if [[ "${dry_run_output}" != *"${target_chart}"* ]]; then
    echo "Expected dry run output to contain chart '${target_chart}'" >&2
    exit 1
fi

if [[ "${dry_run_output}" == *"chart=chart=${target_chart}"* ]]; then
    echo "Dry run output contained a double chart= prefix" >&2
    exit 1
fi

helm_stub_dir="$(mktemp -d)"
trap 'rm -rf "${helm_stub_dir}"' EXIT

cat > "${helm_stub_dir}/helm" <<'EOF'
#!/usr/bin/env bash
printf 'HELM_ARGS:%s\n' "$*"
EOF
chmod +x "${helm_stub_dir}/helm"

deploy_output="$(
    PATH="${helm_stub_dir}:${PATH}" \
    just _helm-oci-deploy 2>&1 \
        release=dspace namespace=dspace \
        chart="${target_chart}" \
        values="${values_arg}" \
        version_file=docs/apps/dspace.version \
        default_tag=v3-latest
)"

if [[ "${deploy_output}" != *"HELM_ARGS:upgrade dspace ${target_chart} --namespace dspace"* ]]; then
    echo "Helm invocation missing expected chart argument" >&2
    exit 1
fi

if [[ "${deploy_output}" == *"chart=${target_chart}"* ]] || \
   [[ "${deploy_output}" == *"chart=chart=${target_chart}"* ]]; then
    echo "Helm invocation still contained a chart= prefix" >&2
    exit 1
fi

echo "helm-oci-install dry run and execution output look correct"
