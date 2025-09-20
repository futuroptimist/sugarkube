#!/usr/bin/env bats

sample_config() {
  cat <<'YAML'
apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: LS0tLQ==
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
    client-certificate-data: LS0tLQ==
    client-key-data: LS0tLQ==
YAML
}

@test "export_sanitized_kubeconfig honors explicit server override" {
  tmp="$(mktemp -d)"
  sample_config >"$tmp/k3s.yaml"

  run env \
    SUGARKUBE_KUBECONFIG_SOURCE="$tmp/k3s.yaml" \
    SUGARKUBE_KUBECONFIG_DEST_DIR="$tmp/boot/sugarkube" \
    SUGARKUBE_KUBECONFIG_PATH="$tmp/boot/sugarkube/kubeconfig" \
    SUGARKUBE_KUBECONFIG_SECONDARY="$tmp/boot/sugarkube-kubeconfig" \
    SUGARKUBE_KUBECONFIG_LOG="$tmp/log" \
    SUGARKUBE_KUBECONFIG_TIMEOUT=1 \
    SUGARKUBE_KUBECONFIG_SERVER="https://192.0.2.10:6443" \
    "$BATS_TEST_DIRNAME/../scripts/export_sanitized_kubeconfig.sh"

  [ "$status" -eq 0 ]
  [ -f "$tmp/boot/sugarkube/kubeconfig" ]
  [ -f "$tmp/boot/sugarkube-kubeconfig" ]
  grep -q "https://192.0.2.10:6443" "$tmp/boot/sugarkube/kubeconfig"
  grep -q "https://192.0.2.10:6443" "$tmp/boot/sugarkube-kubeconfig"
}

@test "export_sanitized_kubeconfig falls back to hostname" {
  tmp="$(mktemp -d)"
  bin="$tmp/bin"
  mkdir -p "$bin"

  cat <<'SH' >"$bin/hostname"
#!/usr/bin/env bash
if [ "$1" = "-I" ]; then
  exit 0
fi
printf 'sugarkube-test'
SH
  chmod +x "$bin/hostname"

  sample_config >"$tmp/k3s.yaml"

  orig_path="$PATH"
  run env \
    PATH="$bin:$orig_path" \
    SUGARKUBE_KUBECONFIG_SOURCE="$tmp/k3s.yaml" \
    SUGARKUBE_KUBECONFIG_DEST_DIR="$tmp/boot/sugarkube" \
    SUGARKUBE_KUBECONFIG_PATH="$tmp/boot/sugarkube/kubeconfig" \
    SUGARKUBE_KUBECONFIG_SECONDARY="$tmp/boot/sugarkube-kubeconfig" \
    SUGARKUBE_KUBECONFIG_LOG="$tmp/log" \
    SUGARKUBE_KUBECONFIG_TIMEOUT=1 \
    "$BATS_TEST_DIRNAME/../scripts/export_sanitized_kubeconfig.sh"

  [ "$status" -eq 0 ]
  grep -q "https://sugarkube-test.local:6443" "$tmp/boot/sugarkube/kubeconfig"
}
