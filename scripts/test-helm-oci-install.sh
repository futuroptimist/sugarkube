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
fixture_registry="${tmp_bin}/dspace-0.0.0.tgz"
status_mode_file="${tmp_bin}/helm-status-mode"

if ! python3 - "${fixture_registry}" <<'PY'
import io
import pathlib
import sys
import tarfile

fixture = sys.argv[1]
chart_files = {
    "dspace/Chart.yaml": "apiVersion: v2\nname: dspace\nversion: 0.0.0\n",
    "dspace/values.yaml": (
        "image:\n"
        "  repository: ghcr.io/democratizedspace/dspace\n"
        "  tag: latest\n"
    ),
}

path = pathlib.Path(fixture)
path.parent.mkdir(parents=True, exist_ok=True)

with tarfile.open(path, mode="w:gz") as archive:
    for name, content in chart_files.items():
        data = content.encode("utf-8")
        info = tarfile.TarInfo(name=name)
        info.size = len(data)
        info.mtime = 0
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(data))

with tarfile.open(fixture, mode="r:gz") as archive:
    names = archive.getnames()
    assert "dspace/Chart.yaml" in names, "missing dspace/Chart.yaml"
PY
then
    echo "Failed to generate valid fake registry fixture: ${fixture_registry}" >&2
    exit 1
fi

cat >"${tmp_bin}/helm" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

status_mode="${HELM_STATUS_MODE:-deployed}"
if [ -n "${HELM_STATUS_MODE_FILE:-}" ] && [ -f "${HELM_STATUS_MODE_FILE}" ]; then
    status_mode="$(cat "${HELM_STATUS_MODE_FILE}")"
fi

if [ "$1" = "-n" ] && [ "$3" = "status" ]; then
    if [ "${status_mode}" = "missing" ]; then
        echo "Error: release: not found" >&2
        exit 1
    fi

    if [ "${status_mode}" = "error" ]; then
        echo "Error: Kubernetes cluster unreachable" >&2
        exit 1
    fi

    if [ "${status_mode}" = "failed" ]; then
        echo "STATUS: failed"
        exit 0
    fi

    echo "STATUS: deployed"
    exit 0
fi

if [[ "${*}" != *"oci://registry.test/charts/dspace"* ]]; then
    echo "Expected fake OCI chart URL in helm args, got: $*" >&2
    exit 1
fi

if [ ! -f "${FAKE_HELM_REGISTRY_CHART:-}" ]; then
    echo "Fake registry chart fixture is missing: ${FAKE_HELM_REGISTRY_CHART:-}" >&2
    exit 1
fi

echo "helm $*" | tee -a "${HELM_TEST_LOG:-/dev/null}"
SH
chmod +x "${tmp_bin}/helm"

cat >"${tmp_bin}/kubectl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

echo "kubectl $*" >> "${KUBECTL_TEST_LOG:-/dev/null}"

if [ "$1" = "-n" ] && [ "$2" = "dspace" ] && [ "$3" = "get" ] && [ "$4" = "deploy,statefulset,daemonset" ] && [ "$5" = "-l" ] && [ "$6" = "app.kubernetes.io/instance=dspace" ]; then
    exit 0
fi

if [ "$1" = "-n" ] && [ "$2" = "dspace" ] && [ "$3" = "get" ] && [ "$4" = "deploy,statefulset,daemonset" ] && [ "$5" = "-l" ] && [ "$6" = "release=dspace" ]; then
    echo "deployment.apps/dspace"
    exit 0
fi

if [ "$1" = "-n" ] && [ "$2" = "dspace" ] && [ "$3" = "rollout" ] && [ "$4" = "status" ] && [ "$5" = "deployment.apps/dspace" ]; then
    echo "deployment \"dspace\" successfully rolled out"
    exit 0
fi

if [ "$1" = "-n" ] && [ "$2" = "dspace" ] && [ "$3" = "get" ] && [ "$4" = "deploy" ] && [ "$5" = "dspace" ]; then
    exit 0
fi

exit 0
SH
chmod +x "${tmp_bin}/kubectl"

command_output="$(
    PATH="${tmp_bin}:${PATH}" HELM_TEST_LOG="${helm_log}" KUBECTL_TEST_LOG="${kubectl_log}" \
        HELM_STATUS_MODE_FILE="${status_mode_file}" \
        FAKE_HELM_REGISTRY_CHART="${fixture_registry}" KUBECONFIG="${tmp_bin}/kubeconfig" \
        just helm-oci-install \
        release=dspace namespace=dspace \
        chart=oci://registry.test/charts/dspace \
        values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml \
        version_file=docs/apps/dspace.version \
        default_tag=v3-latest
)"

if ! grep -q "oci://registry.test/charts/dspace" <<<"${command_output}"; then
    printf 'Expected chart argument missing from generated output.\nOutput:\n%s\n' "${command_output}" >&2
    exit 1
fi

if grep -Eq "chart=oci://|chart=chart=oci://" <<<"${command_output}"; then
    printf 'Found unexpected chart= prefix in generated output.\nOutput:\n%s\n' "${command_output}" >&2
    exit 1
fi

if ! grep -q "oci://registry.test/charts/dspace" "${helm_log}"; then
    printf 'Stubbed helm did not receive expected chart argument.\nLog:\n%s\n' "$(cat "${helm_log}" 2>/dev/null || true)" >&2
    exit 1
fi

if grep -Eq "chart=oci://|chart=chart=oci://" "${helm_log}"; then
    printf 'Stubbed helm received chart argument with unexpected prefix.\nLog:\n%s\n' "$(cat "${helm_log}" 2>/dev/null || true)" >&2
    exit 1
fi

if ! grep -q "Waiting for rollout completion" <<<"${command_output}"; then
    printf 'Expected rollout wait feedback missing.\nOutput:\n%s\n' "${command_output}" >&2
    exit 1
fi

if ! grep -q "get deploy,statefulset,daemonset -l app.kubernetes.io/instance=dspace" "${kubectl_log}"; then
    printf 'Expected app.kubernetes.io/instance selector missing from kubectl calls.\nLog:\n%s\n' "$(cat "${kubectl_log}" 2>/dev/null || true)" >&2
    exit 1
fi

if ! grep -q "get deploy,statefulset,daemonset -l release=dspace" "${kubectl_log}"; then
    printf 'Expected release= selector fallback missing from kubectl calls.\nLog:\n%s\n' "$(cat "${kubectl_log}" 2>/dev/null || true)" >&2
    exit 1
fi

if ! grep -q "rollout status deployment.apps/dspace" "${kubectl_log}"; then
    printf 'Expected rollout status check missing from kubectl calls.\nLog:\n%s\n' "$(cat "${kubectl_log}" 2>/dev/null || true)" >&2
    exit 1
fi

printf 'deployed' >"${status_mode_file}"
upgrade_output="$(
    PATH="${tmp_bin}:${PATH}" HELM_TEST_LOG="${helm_log}" KUBECTL_TEST_LOG="${kubectl_log}" \
        HELM_STATUS_MODE_FILE="${status_mode_file}" \
        FAKE_HELM_REGISTRY_CHART="${fixture_registry}" KUBECONFIG="${tmp_bin}/kubeconfig" \
        just helm-oci-upgrade \
        release=release=dspace namespace=namespace=dspace \
        chart=chart=oci://registry.test/charts/dspace \
        values=values=docs/examples/dspace.values.dev.yaml \
        version_file=version_file=docs/apps/dspace.version
)"

if ! grep -q "helm upgrade dspace oci://registry.test/charts/dspace --namespace dspace --reuse-values" <<<"${upgrade_output}"; then
    printf 'Upgrade path did not preserve expected behavior and argument normalization.\nOutput:\n%s\n' "${upgrade_output}" >&2
    exit 1
fi

printf 'missing' >"${status_mode_file}"
if PATH="${tmp_bin}:${PATH}" HELM_TEST_LOG="${helm_log}" KUBECTL_TEST_LOG="${kubectl_log}" \
    HELM_STATUS_MODE_FILE="${status_mode_file}" \
    FAKE_HELM_REGISTRY_CHART="${fixture_registry}" KUBECONFIG="${tmp_bin}/kubeconfig" \
    just helm-oci-upgrade \
    release=dspace namespace=dspace \
    chart=oci://registry.test/charts/dspace \
    values=docs/examples/dspace.values.dev.yaml \
    version_file=docs/apps/dspace.version >"${tmp_bin}/upgrade-missing.out" 2>&1; then
    printf 'Expected upgrade-only path to fail when release is missing.\n' >&2
    exit 1
fi

if ! grep -q "helm-oci-upgrade requires an existing deployed release" "${tmp_bin}/upgrade-missing.out"; then
    printf 'Missing fresh-cluster actionable error text.\nOutput:\n%s\n' "$(cat "${tmp_bin}/upgrade-missing.out")" >&2
    exit 1
fi

if ! grep -q "just helm-oci-install release=dspace namespace=dspace chart=oci://registry.test/charts/dspace" "${tmp_bin}/upgrade-missing.out"; then
    printf 'Missing install guidance in upgrade-only failure output.\nOutput:\n%s\n' "$(cat "${tmp_bin}/upgrade-missing.out")" >&2
    exit 1
fi


printf 'failed' >"${status_mode_file}"
if PATH="${tmp_bin}:${PATH}" HELM_TEST_LOG="${helm_log}" KUBECTL_TEST_LOG="${kubectl_log}" \
    HELM_STATUS_MODE_FILE="${status_mode_file}" \
    FAKE_HELM_REGISTRY_CHART="${fixture_registry}" KUBECONFIG="${tmp_bin}/kubeconfig" \
    just helm-oci-upgrade \
    release=dspace namespace=dspace \
    chart=oci://registry.test/charts/dspace \
    values=docs/examples/dspace.values.dev.yaml \
    version_file=docs/apps/dspace.version >"${tmp_bin}/upgrade-failed-status.out" 2>&1; then
    printf 'Expected upgrade-only path to fail when release status is not deployed.\n' >&2
    exit 1
fi

if ! grep -q "is 'failed', not 'deployed'" "${tmp_bin}/upgrade-failed-status.out"; then
    printf 'Missing non-deployed status guidance.\nOutput:\n%s\n' "$(cat "${tmp_bin}/upgrade-failed-status.out")" >&2
    exit 1
fi

if ! grep -q "values=docs/examples/dspace.values.dev.yaml" "${tmp_bin}/upgrade-failed-status.out"; then
    printf 'Install guidance did not preserve values argument.\nOutput:\n%s\n' "$(cat "${tmp_bin}/upgrade-failed-status.out")" >&2
    exit 1
fi

if ! grep -q "version_file=docs/apps/dspace.version" "${tmp_bin}/upgrade-failed-status.out"; then
    printf 'Install guidance did not preserve version_file argument.\nOutput:\n%s\n' "$(cat "${tmp_bin}/upgrade-failed-status.out")" >&2
    exit 1
fi

printf 'error' >"${status_mode_file}"
if PATH="${tmp_bin}:${PATH}" HELM_TEST_LOG="${helm_log}" KUBECTL_TEST_LOG="${kubectl_log}" \
    HELM_STATUS_MODE_FILE="${status_mode_file}" \
    FAKE_HELM_REGISTRY_CHART="${fixture_registry}" KUBECONFIG="${tmp_bin}/kubeconfig" \
    just helm-oci-upgrade \
    release=dspace namespace=dspace \
    chart=oci://registry.test/charts/dspace >"${tmp_bin}/upgrade-status-error.out" 2>&1; then
    printf 'Expected upgrade-only path to fail on generic helm status error.\n' >&2
    exit 1
fi

if ! grep -q "could not verify release 'dspace'" "${tmp_bin}/upgrade-status-error.out"; then
    printf 'Missing generic status error guidance.\nOutput:\n%s\n' "$(cat "${tmp_bin}/upgrade-status-error.out")" >&2
    exit 1
fi

if grep -q "just helm-oci-install" "${tmp_bin}/upgrade-status-error.out"; then
    printf 'Generic status error should not suggest install recovery.\nOutput:\n%s\n' "$(cat "${tmp_bin}/upgrade-status-error.out")" >&2
    exit 1
fi

printf 'helm-oci helpers handle install/upgrade/fresh-cluster paths with actionable messaging.\n'
