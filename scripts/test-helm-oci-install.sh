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

printf 'helm-oci-install emits normalized chart argument and rollout feedback.\n'
