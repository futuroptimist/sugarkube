#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

if ! command -v just >/dev/null 2>&1; then
    echo "The 'just' command is required to run this test." >&2
    exit 1
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT
tmp_bin="${tmp_dir}/bin"
mkdir -p "${tmp_bin}"
helm_log="${tmp_dir}/helm.log"
kubectl_log="${tmp_dir}/kubectl.log"
home_dir="${tmp_dir}/home"
mkdir -p "${home_dir}"

cat >"${tmp_bin}/sudo" <<'SH_STUB'
#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -eq 0 ]; then
    exit 0
fi

case "$1" in
    cp)
        dest="${3:-}"
        if [ -z "${dest}" ]; then
            exit 1
        fi
        mkdir -p "$(dirname "${dest}")"
        cat >"${dest}" <<'KUBECONFIG'
apiVersion: v1
kind: Config
clusters:
- name: default
  cluster:
    server: https://127.0.0.1:6443
contexts:
- name: default
  context:
    cluster: default
    user: default
current-context: default
users:
- name: default
  user: {}
KUBECONFIG
        ;;
    chown|chmod)
        ;;
    test)
        shift
        test "$@"
        ;;
    *)
        "$@"
        ;;
esac
SH_STUB
chmod +x "${tmp_bin}/sudo"

cat >"${tmp_bin}/helm" <<'SH_STUB'
#!/usr/bin/env bash
set -euo pipefail

if [ "$1" = "-n" ] && [ "$3" = "status" ]; then
    echo "STATUS: deployed"
    exit 0
fi

echo "helm $*" >> "${HELM_TEST_LOG:-/dev/null}"
SH_STUB
chmod +x "${tmp_bin}/helm"

cat >"${tmp_bin}/kubectl" <<'SH_STUB'
#!/usr/bin/env bash
set -euo pipefail

echo "kubectl $*" >> "${KUBECTL_TEST_LOG:-/dev/null}"

if [ "$1" = "-n" ] && [ "$3" = "get" ] && [ "$4" = "deploy,statefulset,daemonset" ]; then
    if [ "${*: -1}" = "name" ]; then
        echo "deployment.apps/danielsmith"
    elif [[ "$*" == *"jsonpath"* ]]; then
        echo "Deployment/danielsmith"
    fi
    exit 0
fi

if [ "$1" = "-n" ] && [ "$3" = "rollout" ] && [ "$4" = "status" ]; then
    echo "deployment \"danielsmith\" successfully rolled out"
    exit 0
fi

if [ "$1" = "-n" ] && [ "$3" = "get" ] && [ "$4" = "deployment.apps/danielsmith" ]; then
    echo "danielsmith=ghcr.io/futuroptimist/danielsmith.io:main-deadbee"
    exit 0
fi

if [ "$1" = "-n" ] && [ "$3" = "get" ] && [ "$4" = "ingress" ]; then
    exit 0
fi

exit 0
SH_STUB
chmod +x "${tmp_bin}/kubectl"

run_with_stubs() {
    PATH="${tmp_bin}:${PATH}" \
    HOME="${home_dir}" \
    USER="${USER:-sugarkube}" \
    HELM_TEST_LOG="${helm_log}" \
    KUBECTL_TEST_LOG="${kubectl_log}" \
    KUBECONFIG="${home_dir}/.kube/config" \
        just "$@"
}

assert_helm_tag() {
    local expected_tag="$1"
    local latest_line
    latest_line="$(tail -n1 "${helm_log}")"
    if [[ "${latest_line}" != *"--set image.tag=${expected_tag}"* ]]; then
        printf 'Expected latest helm call to set image.tag=%s.\nLatest helm call:\n%s\n' \
            "${expected_tag}" "${latest_line}" >&2
        exit 1
    fi
    if [[ "${latest_line}" == *"image.tag=tag="* ]]; then
        printf 'Helm call still contained a tag= prefix.\nLatest helm call:\n%s\n' \
            "${latest_line}" >&2
        exit 1
    fi
}

run_with_stubs danielsmith-oci-deploy env=staging tag=main-deadbee >"${tmp_dir}/deploy-named.out"
assert_helm_tag "main-deadbee"

run_with_stubs danielsmith-oci-deploy staging main-deadbee >"${tmp_dir}/deploy-positional.out"
assert_helm_tag "main-deadbee"

run_with_stubs danielsmith-oci-redeploy env=staging tag=tag=main-deadbee >"${tmp_dir}/redeploy-named.out"
assert_helm_tag "main-deadbee"

run_with_stubs danielsmith-oci-promote-prod tag=tag=main-deadbee >"${tmp_dir}/promote-named.out"
assert_helm_tag "main-deadbee"

for mutable_tag in tag=main-latest tag=latest tag=main; do
    if run_with_stubs danielsmith-oci-deploy env=staging "${mutable_tag}" \
        >"${tmp_dir}/mutable.out" 2>"${tmp_dir}/mutable.err"; then
        printf 'Expected mutable Danielsmith tag to be rejected: %s\n' "${mutable_tag}" >&2
        exit 1
    fi
    if ! grep -q "mutable tag" "${tmp_dir}/mutable.err"; then
        printf 'Mutable tag rejection did not explain the immutable-tag policy for %s.\nOutput:\n%s\n' \
            "${mutable_tag}" "$(cat "${tmp_dir}/mutable.err")" >&2
        exit 1
    fi
done

printf 'Danielsmith OCI wrappers normalize named tag arguments and still reject mutable tags.\n'
