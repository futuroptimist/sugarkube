#!/usr/bin/env bats

setup() {
  tmp_dir="$(mktemp -d)"
}

teardown() {
  rm -rf "$tmp_dir"
}

@test "export_kubeconfig rewrites server and adds header" {
  mkdir -p "$tmp_dir/etc/rancher/k3s" "$tmp_dir/boot"
  cat <<'YAML' > "$tmp_dir/etc/rancher/k3s/k3s.yaml"
apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: ZmFrZS1jYQ==
    server: https://127.0.0.1:6443
  name: default
contexts:
- context:
    cluster: default
    user: default
  name: default
current-context: default
users:
- name: default
  user:
    client-key-data: ZmFrZS1rZXk=
YAML

  run env \
    SUGARKUBE_KUBECONFIG_SOURCE="$tmp_dir/etc/rancher/k3s/k3s.yaml" \
    SUGARKUBE_KUBECONFIG_DEST="$tmp_dir/boot/sugarkube-kubeconfig" \
    SUGARKUBE_KUBECONFIG_TIMEOUT=1 \
    SUGARKUBE_KUBECONFIG_INTERVAL=0 \
    SUGARKUBE_KUBECONFIG_SERVER="https://example.local:6443" \
    "$BATS_TEST_DIRNAME/../scripts/export_kubeconfig.sh"

  [ "$status" -eq 0 ]
  [ -f "$tmp_dir/boot/sugarkube-kubeconfig" ]
  grep -q "https://example.local:6443" "$tmp_dir/boot/sugarkube-kubeconfig"
  head -n1 "$tmp_dir/boot/sugarkube-kubeconfig" | grep '# sugarkube kubeconfig'
}

@test "export_kubeconfig times out when kubeconfig is missing" {
  run env \
    SUGARKUBE_KUBECONFIG_SOURCE="$tmp_dir/etc/rancher/k3s/k3s.yaml" \
    SUGARKUBE_KUBECONFIG_DEST="$tmp_dir/boot/sugarkube-kubeconfig" \
    SUGARKUBE_KUBECONFIG_TIMEOUT=0 \
    SUGARKUBE_KUBECONFIG_INTERVAL=0 \
    "$BATS_TEST_DIRNAME/../scripts/export_kubeconfig.sh"

  [ "$status" -ne 0 ]
  [[ "$output" == *"Timed out"* ]]
}
