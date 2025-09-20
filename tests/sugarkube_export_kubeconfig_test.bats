#!/usr/bin/env bats

setup() {
  TEST_TMPDIR="$(mktemp -d)"
}

teardown() {
  rm -rf "$TEST_TMPDIR"
}

@test "sugarkube_export_kubeconfig rewrites server and writes legacy copy" {
  local source="$TEST_TMPDIR/k3s.yaml"
  cat <<'YAML' >"$source"
apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: Zm9v
    server: https://127.0.0.1:6443
  name: default
contexts:
- context:
    cluster: default
    user: default
  name: default
current-context: default
kind: Config
preferences: {}
users:
- name: default
  user:
    bearer: PLACEHOLDER_VALUE
YAML

  mkdir -p "$TEST_TMPDIR/legacy"
  local dest="$TEST_TMPDIR/exported.yaml"
  local legacy="$TEST_TMPDIR/legacy/kubeconfig"

  run env \
    SUGARKUBE_KUBECONFIG_SOURCE="$source" \
    SUGARKUBE_KUBECONFIG_DEST="$dest" \
    SUGARKUBE_LEGACY_KUBECONFIG="$legacy" \
    SUGARKUBE_API_HOST="sugarkube.example" \
    SUGARKUBE_KUBECONFIG_WAIT_SECS=1 \
    "$BATS_TEST_DIRNAME/../scripts/sugarkube_export_kubeconfig.sh"

  [ "$status" -eq 0 ]
  grep -q "# API endpoint: https://sugarkube.example:6443" "$dest"
  grep -q "server: https://sugarkube.example:6443" "$dest"
  [ -f "$legacy" ]
  cmp -s "$dest" "$legacy"
}

@test "sugarkube_export_kubeconfig honors endpoint override" {
  local source="$TEST_TMPDIR/k3s.yaml"
  cat <<'YAML' >"$source"
apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: Zm9v
    server: https://127.0.0.1:6443
  name: default
contexts:
- context:
    cluster: default
    user: default
  name: default
current-context: default
kind: Config
preferences: {}
users:
- name: default
  user:
    bearer: PLACEHOLDER_VALUE
YAML

  local dest="$TEST_TMPDIR/exported.yaml"
  local endpoint="https://custom.example:7443"

  run env \
    SUGARKUBE_KUBECONFIG_SOURCE="$source" \
    SUGARKUBE_KUBECONFIG_DEST="$dest" \
    SUGARKUBE_API_ENDPOINT="$endpoint" \
    SUGARKUBE_KUBECONFIG_WAIT_SECS=1 \
    "$BATS_TEST_DIRNAME/../scripts/sugarkube_export_kubeconfig.sh"

  [ "$status" -eq 0 ]
  grep -q "# API endpoint: $endpoint" "$dest"
  grep -q "server: $endpoint" "$dest"
}
