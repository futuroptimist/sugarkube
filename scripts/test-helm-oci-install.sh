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

python3 - "${fixture_registry}" <<'PY'
import io, pathlib, sys, tarfile
fixture = sys.argv[1]
chart_files = {
    "dspace/Chart.yaml": "apiVersion: v2\nname: dspace\nversion: 0.0.0\n",
    "dspace/values.yaml": "image:\n  repository: ghcr.io/democratizedspace/dspace\n  tag: latest\n",
}
path = pathlib.Path(fixture)
path.parent.mkdir(parents=True, exist_ok=True)
with tarfile.open(path, mode="w:gz") as archive:
    for name, content in chart_files.items():
        data = content.encode()
        info = tarfile.TarInfo(name=name)
        info.size = len(data)
        info.mtime = 0
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(data))
PY

cat >"${tmp_bin}/helm" <<'SH2'
#!/usr/bin/env bash
set -euo pipefail

echo "helm $*" >> "${HELM_TEST_LOG:-/dev/null}"

if [ "$1" = "-n" ] && [ "$2" = "dspace" ] && [ "$3" = "status" ] && [ "$4" = "dspace" ] && [ "$5" = "-o" ] && [ "$6" = "json" ]; then
    case "${HELM_STATUS_MODE:-deployed}" in
        missing) exit 1 ;;
        failed) printf '{"info":{"status":"failed"}}\n'; exit 0 ;;
        deployed) printf '{"info":{"status":"deployed"}}\n'; exit 0 ;;
    esac
fi

if [[ "$*" != *"oci://registry.test/charts/dspace"* ]]; then
    echo "Expected fake OCI chart URL in helm args, got: $*" >&2
    exit 1
fi

if [ ! -f "${FAKE_HELM_REGISTRY_CHART:-}" ]; then
    echo "Fake registry chart fixture is missing: ${FAKE_HELM_REGISTRY_CHART:-}" >&2
    exit 1
fi
SH2
chmod +x "${tmp_bin}/helm"

cat >"${tmp_bin}/kubectl" <<'SH2'
#!/usr/bin/env bash
set -euo pipefail

echo "kubectl $*" >> "${KUBECTL_TEST_LOG:-/dev/null}"
if [ "$1" = "-n" ] && [ "$2" = "dspace" ] && [ "$3" = "get" ] && [ "$4" = "deploy,statefulset,daemonset" ] && [ "$5" = "-l" ] && [ "$6" = "app.kubernetes.io/instance=dspace" ]; then exit 0; fi
if [ "$1" = "-n" ] && [ "$2" = "dspace" ] && [ "$3" = "get" ] && [ "$4" = "deploy,statefulset,daemonset" ] && [ "$5" = "-l" ] && [ "$6" = "release=dspace" ]; then echo "deployment.apps/dspace"; exit 0; fi
if [ "$1" = "-n" ] && [ "$2" = "dspace" ] && [ "$3" = "rollout" ] && [ "$4" = "status" ] && [ "$5" = "deployment.apps/dspace" ]; then exit 0; fi
exit 0
SH2
chmod +x "${tmp_bin}/kubectl"

common_env=(PATH="${tmp_bin}:${PATH}" HELM_TEST_LOG="${helm_log}" KUBECTL_TEST_LOG="${kubectl_log}" FAKE_HELM_REGISTRY_CHART="${fixture_registry}" KUBECONFIG="${tmp_bin}/kubeconfig")

install_output="$(env "${common_env[@]}" just helm-oci-install release=dspace namespace=dspace chart=oci://registry.test/charts/dspace values=docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml version_file=docs/apps/dspace.version default_tag=v3-latest)"
grep -q -- '--install --create-namespace' "${helm_log}"

echo -n > "${helm_log}"
upgrade_output="$(env HELM_STATUS_MODE=deployed "${common_env[@]}" just helm-oci-upgrade release=dspace namespace=dspace chart=oci://registry.test/charts/dspace values=docs/examples/dspace.values.staging.yaml version_file=docs/apps/dspace.version default_tag=main-92a1bcb)"
grep -q -- 'helm -n dspace status dspace -o json' "${helm_log}"
grep -q -- '--reuse-values' "${helm_log}"

echo -n > "${helm_log}"
set +e
missing_output="$(env HELM_STATUS_MODE=missing "${common_env[@]}" just helm-oci-upgrade release=dspace namespace=dspace chart=oci://registry.test/charts/dspace values=docs/examples/dspace.values.staging.yaml version_file=docs/apps/dspace.version default_tag=main-92a1bcb 2>&1)"
missing_status=$?
set -e
[ "${missing_status}" -ne 0 ]
grep -q "has no deployed revision" <<<"${missing_output}"
grep -q "just helm-oci-install" <<<"${missing_output}"
if grep -q "helm upgrade dspace" "${helm_log}"; then
  echo "upgrade command should not run when release is missing" >&2
  exit 1
fi

printf 'helm-oci-install/upgrade handles fresh-cluster recovery preflight and normalization.\n'
