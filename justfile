set shell := ["bash", "-euo", "pipefail", "-c"]
set export := true

export SUGARKUBE_CLUSTER := env('SUGARKUBE_CLUSTER', 'sugar')
export SUGARKUBE_SERVERS := env('SUGARKUBE_SERVERS', '1')
export K3S_CHANNEL := env('K3S_CHANNEL', 'stable')
export SUGARKUBE_MDNS_ABSENCE_GATE := env('SUGARKUBE_MDNS_ABSENCE_GATE', '1')
export SUGARKUBE_MDNS_ABSENCE_TIMEOUT_MS := env('SUGARKUBE_MDNS_ABSENCE_TIMEOUT_MS', '15000')
export SUGARKUBE_MDNS_ABSENCE_BACKOFF_START_MS := env('SUGARKUBE_MDNS_ABSENCE_BACKOFF_START_MS', '500')
export SUGARKUBE_MDNS_ABSENCE_BACKOFF_CAP_MS := env('SUGARKUBE_MDNS_ABSENCE_BACKOFF_CAP_MS', '4000')
export SUGARKUBE_MDNS_ABSENCE_JITTER := env('SUGARKUBE_MDNS_ABSENCE_JITTER', '0.25')
export SUGARKUBE_MDNS_ABSENCE_DBUS := env('SUGARKUBE_MDNS_ABSENCE_DBUS', '1')

default: up
    @true

up env='dev':
    #!/usr/bin/env bash
    set -Eeuo pipefail

    # Select per-environment token if available
    if [ "{{ env }}" = "dev" ] && [ -n "${SUGARKUBE_TOKEN_DEV:-}" ]; then export SUGARKUBE_TOKEN="$SUGARKUBE_TOKEN_DEV"; fi
    if [ "{{ env }}" = "int" ] && [ -n "${SUGARKUBE_TOKEN_INT:-}" ]; then export SUGARKUBE_TOKEN="$SUGARKUBE_TOKEN_INT"; fi
    if [ "{{ env }}" = "prod" ] && [ -n "${SUGARKUBE_TOKEN_PROD:-}" ]; then export SUGARKUBE_TOKEN="$SUGARKUBE_TOKEN_PROD"; fi

    export SUGARKUBE_ENV="{{ env }}"
    export SUGARKUBE_SERVERS="{{ SUGARKUBE_SERVERS }}"

    export SUGARKUBE_SUMMARY_FILE="$(mktemp -t sugarkube-summary.XXXXXX)"

    if [ -z "${SUGARKUBE_SUMMARY_LIB:-}" ] && [ -f "{{ invocation_directory() }}/scripts/lib/summary.sh" ]; then
        SUGARKUBE_SUMMARY_LIB="{{ invocation_directory() }}/scripts/lib/summary.sh"
    fi
    : "${SUGARKUBE_SUMMARY_LIB:=/home/pi/sugarkube/scripts/lib/summary.sh}"
    if [ ! -f "${SUGARKUBE_SUMMARY_LIB}" ] && [ -f "/home/pi/sugarkube/scripts/lib/summary.sh" ]; then
        SUGARKUBE_SUMMARY_LIB="/home/pi/sugarkube/scripts/lib/summary.sh"
    fi
    export SUGARKUBE_SUMMARY_LIB

    if [ "${SAVE_DEBUG_LOGS:-0}" = "1" ]; then
        if [ -z "${SUGARKUBE_LOG_FILTER:-}" ] && [ -f "{{ invocation_directory() }}/scripts/filter_debug_log.py" ]; then
            SUGARKUBE_LOG_FILTER="{{ invocation_directory() }}/scripts/filter_debug_log.py"
        fi
        : "${SUGARKUBE_LOG_FILTER:=/home/pi/sugarkube/scripts/filter_debug_log.py}"
        if [ ! -f "${SUGARKUBE_LOG_FILTER}" ] && [ -f "/home/pi/sugarkube/scripts/filter_debug_log.py" ]; then
            SUGARKUBE_LOG_FILTER="/home/pi/sugarkube/scripts/filter_debug_log.py"
        fi
        if [ -f "${SUGARKUBE_LOG_FILTER}" ]; then
            : "${SAVE_DEBUG_LOGS_DIR:=logs/up}"
            if mkdir -p "${SAVE_DEBUG_LOGS_DIR}" 2>/dev/null; then
                commit_hash="$(git -C "{{ invocation_directory() }}" rev-parse --short HEAD 2>/dev/null || git rev-parse --short HEAD 2>/dev/null || echo unknown)"
                timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
                hostname_safe="$(hostname | tr ' ' '-' | tr -cd '[:alnum:]._-')"
                log_basename="${timestamp}_${commit_hash}_${hostname_safe}_just-up-${SUGARKUBE_ENV}.log"
                log_dir="${SAVE_DEBUG_LOGS_DIR%/}"
                log_path="${log_dir}/${log_basename}"
                export SUGARKUBE_DEBUG_LOG_FILE="${log_path}"
                exec > >(python3 "${SUGARKUBE_LOG_FILTER}" --log "${log_path}" --source "just up ${SUGARKUBE_ENV}") 2>&1
            else
                printf 'WARNING: SAVE_DEBUG_LOGS=1 but unable to create %s\n' "${SAVE_DEBUG_LOGS_DIR}" >&2
            fi
        else
            printf 'WARNING: SAVE_DEBUG_LOGS=1 but %s is missing\n' "${SUGARKUBE_LOG_FILTER}" >&2
        fi
    fi

    if [ -f "${SUGARKUBE_SUMMARY_LIB}" ]; then
        # shellcheck disable=SC1090
        source "${SUGARKUBE_SUMMARY_LIB}"
    else
        summary::init() { :; }
        summary::section() { :; }
        summary::step() { :; }
        summary::kv() { :; }
        summary::emit() { :; }
    fi

    # Always emit summary on exit (best-effort)
    trap 'summary::emit || true' EXIT

    if ! command -v summary_run >/dev/null 2>&1; then
        summary_run() {
            local _label="$1"
            shift || true
            "$@"
            return "$?"
        }
    fi
    if ! command -v summary_skip >/dev/null 2>&1; then
        summary_skip() { :; }
    fi
    if ! command -v summary_finalize >/dev/null 2>&1; then
        summary_finalize() { :; }
    fi

    __sugarkube_up_cleanup_common() {
        local status="$1"
        if [ "${SUGARKUBE_DISABLE_WLAN_DURING_BOOTSTRAP:-1}" = "1" ] && \
            [ -f "${SUGARKUBE_RUNTIME_DIR:-${SUGARKUBE_RUN_DIR:-/run/sugarkube}}/wlan-disabled" ]; then
            sudo -E bash scripts/toggle_wlan.sh --restore || true
        fi
        if command -v summary::emit >/dev/null 2>&1; then
            summary::emit || true
        elif command -v summary_finalize >/dev/null 2>&1; then
            summary_finalize
        fi
        if [ -n "${SUGARKUBE_SUMMARY_FILE:-}" ]; then
            rm -f "${SUGARKUBE_SUMMARY_FILE}" 2>/dev/null || true
        fi
        if [ "${SAVE_DEBUG_LOGS:-0}" = "1" ] && [ -n "${SUGARKUBE_DEBUG_LOG_FILE:-}" ] && [ -f "${SUGARKUBE_DEBUG_LOG_FILE}" ]; then
            printf '\n[debug] Log saved to %s\n' "${SUGARKUBE_DEBUG_LOG_FILE}" >&2
        fi
        return "${status}"
    }

    __sugarkube_up_exit_trap() {
        local status="$?"
        __sugarkube_up_cleanup_common "${status}"
    }

    __sugarkube_up_signal_trap() {
        local signal="$1"
        local status="$?"
        trap - EXIT INT TERM
        __sugarkube_up_cleanup_common "${status}"
        case "${signal}" in
            INT) exit 130 ;;
            TERM) exit 143 ;;
        esac
    }

    trap '__sugarkube_up_exit_trap' EXIT
    trap '__sugarkube_up_signal_trap INT' INT
    trap '__sugarkube_up_signal_trap TERM' TERM

    summary_run "Dependencies" sudo -E scripts/install_deps.sh

    summary_run "Memory cgroup" "{{ scripts_dir }}/check_memory_cgroup.sh"

    # Preflight network/mDNS configuration
    if [ "${SUGARKUBE_CONFIGURE_AVAHI:-1}" = "1" ]; then
        summary_run "Avahi configure" sudo -E bash scripts/configure_avahi.sh
    else
        summary_skip "Avahi configure" "disabled"
    fi

    # Optionally bring WLAN down for deterministic bootstrap
    if [ "${SUGARKUBE_DISABLE_WLAN_DURING_BOOTSTRAP:-1}" = "1" ]; then
        summary_run "WLAN disable" sudo -E bash scripts/toggle_wlan.sh --down
    else
        summary_skip "WLAN disable" "disabled"
    fi

    if [ "${SUGARKUBE_SET_K3S_NODE_IP:-1}" = "1" ]; then
        summary_run "Node IP configure" sudo -E bash scripts/configure_k3s_node_ip.sh
    else
        summary_skip "Node IP configure" "disabled"
    fi

    # Proceed with discovery/join for subsequent nodes
    summary_run "k3s discover/install" sudo -E bash scripts/k3s-discover.sh

deps:
    sudo -E scripts/install_deps.sh

prereqs:
    @echo "[deprecated] Use 'just deps' instead of 'just prereqs'." >&2
    sudo -E scripts/install_deps.sh

# Check cluster health by displaying all nodes (guards against running before k3s is installed).
status:
    if ! command -v k3s >/dev/null 2>&1; then printf '%s\n' 'k3s is not installed yet.' 'Visit https://github.com/futuroptimist/sugarkube/blob/main/docs/raspi_cluster_setup.md.' 'Follow the instructions in that guide before rerunning this command.'; exit 0; fi
    sudo k3s kubectl get nodes -o wide

# Show a summarized status of the HA cluster, Helm CLI, and Traefik ingress.

# This is a read-only health dashboard for debugging and quick checks.
cluster-status:
    #!/usr/bin/env bash
    set -euo pipefail

    scripts/ensure_user_kubeconfig.sh || true
    if [ -z "${KUBECONFIG:-}" ]; then
        export KUBECONFIG="${HOME}/.kube/config"
    fi

    kubectl_ok=0
    if kubectl version >/dev/null 2>&1; then
        kubectl_ok=1
    fi

    if [ ! -r "${KUBECONFIG}" ]; then
        echo "WARNING: kubeconfig missing at ${KUBECONFIG}; kubectl may fail." >&2
    fi

    echo "=== Cluster nodes (kubectl get nodes) ==="
    if [ "${kubectl_ok}" -eq 0 ]; then
        echo "kubectl is not configured for this cluster (or the API server is unreachable)."
        echo "Check that KUBECONFIG is set correctly and that the k3s server is running."
    else
        kubectl get nodes -o wide
    fi

    echo
    echo "=== Helm status (CLI on this node) ==="
    helm version --short || echo "Helm is not installed or not on PATH."
    which helm || echo "No helm binary found on PATH."

    echo
    echo "=== Traefik status (pods and service in kube-system) ==="
    if [ "${kubectl_ok}" -eq 0 ]; then
        echo "Skipping Traefik checks because kubectl cannot reach the cluster."
    else
        kubectl -n kube-system get pods -l app.kubernetes.io/name=traefik \
          || echo "No Traefik pods"
        kubectl -n kube-system get svc -l app.kubernetes.io/name=traefik \
          || echo "No Traefik service"
    fi

    echo
    echo "=== Ingress classes (cluster-wide) ==="
    if [ "${kubectl_ok}" -eq 0 ]; then
        echo "Skipping ingress class checks because kubectl cannot reach the cluster."
    else
        kubectl get ingressclass || echo "No ingress classes found."
    fi

# Run twice per server during initial bring-up to build a 3-node HA control plane.
ha3 env='dev':
    SUGARKUBE_SERVERS=3 just --justfile "{{ justfile_directory() }}/justfile" up {{ env }}

# Remove the control-plane NoSchedule taint from all nodes so they can run workloads.
# This is intended for the homelab topology where all three HA control-plane nodes

# also act as workers.
ha3-untaint-control-plane:
    #!/usr/bin/env bash
    set -Eeuo pipefail

    scripts/ensure_user_kubeconfig.sh || true

    # Use user kubeconfig if available
    if [ -z "${KUBECONFIG:-}" ] && [ -r "$HOME/.kube/config" ]; then
        export KUBECONFIG="$HOME/.kube/config"
    fi

    # Probe whether kubectl can reach the cluster
    if ! kubectl get nodes >/dev/null 2>&1; then
        echo "ERROR: kubectl cannot reach the cluster (kubectl get nodes failed)." >&2
        echo "Check whether k3s is running and KUBECONFIG is set correctly." >&2
        echo "Tip: if you have a working k3s kubeconfig at /etc/rancher/k3s/k3s.yaml," >&2
        echo "you can create a user kubeconfig with:" >&2
        echo "  sudo mkdir -p \"$HOME/.kube\"" >&2
        echo "  sudo cp /etc/rancher/k3s/k3s.yaml \"$HOME/.kube/config\"" >&2
        echo "  sudo chown \"$(id -u):$(id -g)\" \"$HOME/.kube/config\"" >&2
        echo "  chmod 600 \"$HOME/.kube/config\"" >&2
        echo "Then re-run this command as your normal user." >&2
        exit 1
    fi

    if ! command -v jq >/dev/null 2>&1; then
        echo "ERROR: 'jq' is required but not installed. Please install 'jq' and try again." >&2
        exit 1
    fi

    echo "Untainting control-plane nodes so they can schedule workloads..."

    nodes=$(kubectl get nodes -o name)
    if [ -z "${nodes}" ]; then
        echo "No nodes found. Is the cluster up and kubeconfig configured?" >&2
        exit 1
    fi

    for node in ${nodes}; do
        node_name=${node#node/}

        echo
        echo "Node: ${node_name}"
        echo "Current taints:"
        kubectl get node "${node_name}" \
            -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints

        echo "Removing control-plane/master taints (if present)..."
        kubectl taint nodes "${node_name}" node-role.kubernetes.io/control-plane- || true
        kubectl taint nodes "${node_name}" node-role.kubernetes.io/master- || true

        remaining_taints=$(kubectl get node "${node_name}" -o json | jq -r '
            .spec.taints // []
            | map(select(
                (.key == "node-role.kubernetes.io/control-plane") or
                (.key == "node-role.kubernetes.io/master")
            ))
            | length
        ')

        if [ "${remaining_taints}" -eq 0 ]; then
            echo "Result: ${node_name} has no control-plane/master taints."
        else
            echo "Result: ${node_name} still has control-plane/master taints:"
            kubectl get node "${node_name}" \
                -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
        fi
    done

    echo
    echo "Done. Current node taints:"
    kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints

# Capture sanitized logs to logs/up/ during cluster bring-up (useful for troubleshooting and documentation).
save-logs env='dev':
    SAVE_DEBUG_LOGS=1 just --justfile "{{ justfile_directory() }}/justfile" up {{ env }}

# Display the k3s node token needed for additional nodes to join the cluster.
cat-node-token:
    sudo cat /var/lib/rancher/k3s/server/node-token

mdns-harden:
    sudo -E bash scripts/configure_avahi.sh

mdns-selfcheck env='dev':
    export SUGARKUBE_ENV="{{ env }}"
    env \
    SUGARKUBE_EXPECTED_HOST="$(hostname).local" \
    SUGARKUBE_SELFCHK_ATTEMPTS=10 \
    SUGARKUBE_SELFCHK_BACKOFF_START_MS=500 \
    SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=500 \
    scripts/mdns_selfcheck.sh

node-ip-dropin:
    sudo -E bash scripts/configure_k3s_node_ip.sh

wlan-down:
    sudo -E bash scripts/toggle_wlan.sh --down

wlan-up:
    sudo -E bash scripts/toggle_wlan.sh --restore

mdns-reset:
    sudo bash -lc $'set -e\nif [ -f /etc/avahi/avahi-daemon.conf.bak ]; then\n  cp /etc/avahi/avahi-daemon.conf.bak /etc/avahi/avahi-daemon.conf\n  systemctl restart avahi-daemon\nfi\nfor SVC in k3s.service k3s-agent.service; do\n  if systemctl list-unit-files | grep -q "^$SVC"; then\n    rm -rf "/etc/systemd/system/$SVC.d/10-node-ip.conf" || true\n  fi\ndone\nsystemctl daemon-reload\n'

# Copy k3s kubeconfig to ~/.kube/config and rename context for the specified environment.
kubeconfig env='dev':
    mkdir -p ~/.kube
    sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
    sudo chown -R "$USER":"$USER" ~/.kube
    chmod 700 ~/.kube
    chmod 600 ~/.kube/config
    python3 scripts/update_kubeconfig_scope.py "${HOME}/.kube/config" "sugar-{{ env }}"

origin_cert_guidance := """
  NOTE: cloudflared is still behaving like a locally-managed tunnel (looking for cert.pem / credentials.json).
  This happens when the connector token is invalid for remote-managed mode or the tunnel itself is not set to
  config_src="cloudflare".

  Please verify all of the following:
    - Copy the connector token from the Cloudflare dashboard snippet that looks like:

        cloudflared tunnel --no-autoupdate run --token <TOKEN>

      Copy only <TOKEN> into CF_TUNNEL_TOKEN (not an Access service token, not the full command).
    - In the dashboard/API, confirm the tunnel is remote-managed (config_src="cloudflare"), not a locally-managed
      tunnel created solely with cert.pem + credentials.json. Recreate the tunnel via the remote-managed guide if needed.
    - After correcting the token/tunnel, run:

        just cf-tunnel-reset
        just cf-tunnel-install env=dev token="$CF_TUNNEL_TOKEN"
"""

cf-tunnel-install env='dev' token='':
    #!/usr/bin/env bash
    set -Eeuo pipefail

    export KUBECONFIG="${HOME}/.kube/config"

    origin_cert_guidance="{{ origin_cert_guidance }}"

    : "${token:=${CF_TUNNEL_TOKEN:-}}"
    if [ -z "${token}" ]; then
    echo "Set CF_TUNNEL_TOKEN or pass token=<tunnel-token> to proceed." >&2
    exit 1
    fi

    # Tolerate common Cloudflare dashboard copy/paste patterns so the Secret always gets just the JWT.
    token="$(printf '%s' "${token}" | tr -d '\r\n' | sed -e 's/^ *//' -e 's/ *$//')"
    if printf '%s' "${token}" | grep -qi '^export '; then
    token="${token#export }"
    token="$(printf '%s' "${token}" | sed -e 's/^ *//' -e 's/ *$//')"
    fi
    for prefix in token= TUNNEL_TOKEN= CF_TUNNEL_TOKEN=; do
    case "${token}" in
    ${prefix}*) token="${token#${prefix}}" ;;
    esac
    done
    if printf '%s' "${token}" | grep -q "cloudflared"; then
    token="$(printf '%s' "${token}" | awk '{print $NF}')"
    fi
    # Final whitespace trim after all token transforms
    token="$(printf '%s' "${token}" | sed -e 's/^ *//' -e 's/ *$//')"

    token_len=${#token}
    if [ "${token_len}" -lt 16 ]; then
    echo "ERROR: CF_TUNNEL_TOKEN appears too short; copy the full token from the dashboard." >&2
    exit 1
    fi
    if ! printf '%s' "${token}" | grep -q '^eyJ'; then
    echo "WARNING: CF_TUNNEL_TOKEN does not look like a JWT (missing 'eyJ' prefix)." >&2
    echo "Ensure you copied the connector token from the 'tunnel run --token' snippet." >&2
    fi

    kubectl get namespace cloudflare >/dev/null 2>&1 || kubectl create namespace cloudflare

    kubectl -n cloudflare create secret generic tunnel-token \
    --from-literal=token="${token}" \
    --dry-run=client -o yaml | kubectl apply -f -

    helm repo add cloudflare https://cloudflare.github.io/helm-charts --force-update
    helm repo update cloudflare

    values_yaml=$(printf '%s\n' \
    'fullnameOverride: cloudflare-tunnel' \
    'cloudflare:' \
    "  tunnelName: \"${CF_TUNNEL_NAME:-sugarkube-{{ env }}}\"" \
    "  tunnelId: \"${CF_TUNNEL_ID:-}\"" \
    '  secretName: tunnel-token' \
    '  ingress: []'
    )

    existing=$(helm -n cloudflare list --filter '^cloudflare-tunnel$' --output json 2>/dev/null || true)
    if [ -n "${existing}" ]; then
    status=$(printf '%s\n' "${existing}" | jq -r '.[0].status' 2>/dev/null || echo '')
    if [ -z "${status}" ]; then
    helm_status_output=$(helm -n cloudflare status cloudflare-tunnel 2>/dev/null || true)
    status=$(printf '%s\n' "${helm_status_output}" | grep -oE '^STATUS: (failed|pending-install)' | cut -d' ' -f2 || true)
    fi
    if [ "${status}" = "failed" ] || [ "${status}" = "pending-install" ]; then
    echo "Existing 'cloudflare-tunnel' Helm release is in ${status} state; uninstalling before re-deploy..."
    helm -n cloudflare uninstall cloudflare-tunnel || true
    fi
    fi

    helm_exit_code=0
    if ! helm upgrade --install cloudflare-tunnel cloudflare/cloudflare-tunnel \
    --namespace cloudflare \
    --create-namespace \
    --values - <<<"${values_yaml}"; then
    helm_exit_code=$?
    echo "Helm upgrade/install failed; diagnostics to follow:" >&2
    helm -n cloudflare status cloudflare-tunnel || true
    kubectl -n cloudflare get deploy,po -l app.kubernetes.io/name=cloudflare-tunnel || true
    fi

    if ! kubectl -n cloudflare get deploy cloudflare-tunnel >/dev/null 2>&1; then
    echo "cloudflare-tunnel deployment not found after Helm install; aborting." >&2
    helm -n cloudflare status cloudflare-tunnel || true
    exit 1
    fi

    # Force remote-managed token-mode authentication by injecting the TUNNEL_TOKEN env var and running cloudflared
    # exactly as documented for Kubernetes token deployments. Remove config/creds volumes entirely so the pod never
    # mounts credentials.json or any origin certificate material.
    deployment_patch='[
    {"op":"replace","path":"/spec/template/spec/volumes","value":[]},
    {"op":"replace","path":"/spec/template/spec/containers/0/env","value":[{"name":"TUNNEL_TOKEN","valueFrom":{"secretKeyRef":{"name":"tunnel-token","key":"token"}}}]},
    {"op":"replace","path":"/spec/template/spec/containers/0/volumeMounts","value":[]},
    {"op":"replace","path":"/spec/template/spec/containers/0/image","value":"cloudflare/cloudflared:2024.8.3"},
    {"op":"replace","path":"/spec/template/spec/containers/0/command","value":["cloudflared","tunnel","--no-autoupdate","--metrics","0.0.0.0:2000","run"]},
    {"op":"replace","path":"/spec/template/spec/containers/0/args","value":[]}
    ]'

    kubectl -n cloudflare patch deployment cloudflare-tunnel --type json --patch "${deployment_patch}"

    helm_note_printed=0

    # Allow up to 180s for rollout to complete; this accounts for image pull times and the deployment reaching ready state.
    if ! kubectl -n cloudflare rollout status deployment/cloudflare-tunnel --timeout=180s; then
    echo "cloudflare-tunnel rollout did not become ready; diagnostics:" >&2
    helm -n cloudflare status cloudflare-tunnel || true
    kubectl -n cloudflare get deploy,po -l app.kubernetes.io/name=cloudflare-tunnel || true
    kubectl -n cloudflare logs deploy/cloudflare-tunnel --tail=50 || true

    echo "Attempting teardown + retry: deleting existing pods and retrying rollout..." >&2
    kubectl -n cloudflare delete pod -l app.kubernetes.io/name=cloudflare-tunnel || true

    sleep 5

    if ! kubectl -n cloudflare rollout status deployment/cloudflare-tunnel --timeout=60s; then
    echo "cloudflare-tunnel still failing after teardown+retry; see logs above." >&2
    helm -n cloudflare status cloudflare-tunnel || true
    kubectl -n cloudflare get deploy,po -l app.kubernetes.io/name=cloudflare-tunnel || true
    logs=$(kubectl -n cloudflare logs deploy/cloudflare-tunnel --tail=50 2>/dev/null || true)
    printf '%s\n' "${logs}"

        if printf '%s' "${logs}" | grep -Eq "Cannot determine default origin certificate path|client didn't specify origincert path"; then
            printf '%s\n' "${origin_cert_guidance}" >&2
        fi
    if [ "${helm_exit_code:-0}" -ne 0 ] && [ "${helm_note_printed}" -eq 0 ]; then
    echo "Note: Helm reported errors earlier; token-mode patches still applied." >&2
    helm_note_printed=1
    fi
    exit 1
    fi
    fi

    if [ "${helm_exit_code:-0}" -ne 0 ] && [ "${helm_note_printed}" -eq 0 ]; then
    echo "Note: Helm reported errors earlier; token-mode patches still applied." >&2
    helm_note_printed=1
    fi

    printf '%s\n' \
    'Cloudflare Tunnel chart deployed in token mode.' \
    '- Secret: cloudflare/tunnel-token (key: token)' \
    "- Tunnel name: ${CF_TUNNEL_NAME:-sugarkube-{{ env }}}" \
    '- Verify readiness: kubectl -n cloudflare get deploy,po -l app.kubernetes.io/name=cloudflare-tunnel' \
    '- Readiness endpoint: /ready must return 200'

# Hard reset the Cloudflare Tunnel resources in the cluster for a fresh cf-tunnel-install.
cf-tunnel-reset:
    #!/usr/bin/env bash
    set -Eeuo pipefail

    export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"

    # Delete deployment, pods, and configmap; keep the Secret so the token isn't lost by default.
    kubectl -n cloudflare delete deploy cloudflare-tunnel --ignore-not-found=true
    kubectl -n cloudflare delete pod -l app.kubernetes.io/name=cloudflare-tunnel --ignore-not-found=true
    kubectl -n cloudflare delete configmap cloudflare-tunnel --ignore-not-found=true

    # Optionally, keep this commented out but documented for a full nuke:
    # kubectl -n cloudflare delete secret tunnel-token --ignore-not-found=true

    # Delete the Helm release (if present) to guarantee a clean slate.
    if helm -n cloudflare list --filter '^cloudflare-tunnel$' | grep -q cloudflare-tunnel; then
        helm -n cloudflare uninstall cloudflare-tunnel || true
    fi

    echo "Cloudflare Tunnel reset complete. Re-run 'just cf-tunnel-install env=dev token=\"${CF_TUNNEL_TOKEN:-<your-token>}\"' to reinstall."

# Show Cloudflare Tunnel status and recent logs (for debugging rollout failures).
cf-tunnel-debug:
    #!/usr/bin/env bash
    set -Eeuo pipefail

    export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"

    origin_cert_guidance="{{ origin_cert_guidance }}"

    echo "=== Helm release ==="
    helm -n cloudflare status cloudflare-tunnel || echo "No Helm release."

    echo
    echo "=== Deployment + pods ==="
    kubectl -n cloudflare get deploy,po -l app.kubernetes.io/name=cloudflare-tunnel -o wide || true

    echo
    echo "=== ConfigMap ==="
    echo "No ConfigMap created in token-only mode; configuration is passed via CLI args."

    echo
    echo "=== Deployment container + volumes ==="
    kubectl -n cloudflare get deploy cloudflare-tunnel -o yaml | sed -n '/containers:/,/volumes:/p' || true

    echo
    echo "=== Recent logs from one pod ==="
    POD=$(kubectl -n cloudflare get pods -l app.kubernetes.io/name=cloudflare-tunnel -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    if [ -n "$POD" ]; then
        logs=$(kubectl -n cloudflare logs "$POD" --tail=50 2>/dev/null || true)
        printf '%s\n' "${logs}"

        if printf '%s' "${logs}" | grep -Eq "Cannot determine default origin certificate path|client didn't specify origincert path"; then
            printf '%s\n' "${origin_cert_guidance}" >&2
        fi
    else
        echo "No Cloudflare Tunnel pods to show logs for."
    fi

# Install the Helm CLI on the current node (idempotent; safe to re-run).
helm-install:
    #!/usr/bin/env bash
    set -Eeuo pipefail

    if command -v helm >/dev/null 2>&1; then
        echo "Helm is already installed; nothing to do."
        helm version --short || true
        exit 0
    fi

    echo "Helm not found; installing Helm 3 via the official script..."
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

    echo "Helm installed:"
    helm version --short

# Print the Helm version if installed.
helm-status:
    #!/usr/bin/env bash
    set -Eeuo pipefail

    if command -v helm >/dev/null 2>&1; then
        helm version --short
    else
        echo "Helm is not installed." >&2
        exit 1
    fi

# Diagnose Gateway API CRD ownership for Traefik (read-only; use apply=1 to delete CRDs).
traefik-crd-doctor apply='0' namespace='kube-system':
    #!/usr/bin/env bash
    set -Eeuo pipefail

    crd_lib="{{ justfile_directory() }}/scripts/lib/traefik_crd.sh"
    if [ ! -f "${crd_lib}" ]; then
        echo "ERROR: Traefik CRD helper script missing at ${crd_lib}." >&2
        exit 1
    fi

    if ! command -v kubectl >/dev/null 2>&1; then
        echo "ERROR: kubectl is required to inspect Gateway API CRDs." >&2
        exit 1
    fi

    # shellcheck disable=SC1090
    source "${crd_lib}"

    namespace="{{ namespace }}"
    apply_flag="${TRAEFIK_CRD_DOCTOR_APPLY:-{{ apply }}}"

    traefik_crd::classify_all "${namespace}"
    traefik_crd::print_report "${namespace}" "${apply_flag}"

    if [ "${#TRAEFIK_CRD_PROBLEMS[@]}" -gt 0 ]; then
        echo
        traefik_crd::print_problem_details
        traefik_crd::print_suggestions
    fi

    if [ "${apply_flag}" != "1" ]; then
        if [ "${#TRAEFIK_CRD_PROBLEMS[@]}" -gt 0 ]; then
            exit 1
        fi
        exit 0
    fi

    if [ "${#TRAEFIK_CRD_PROBLEMS[@]}" -eq 0 ]; then
        echo "No problematic Gateway API CRDs detected; nothing to apply."
        exit 0
    fi

    traefik_crd::print_apply_warning
    echo
    echo "Planned destructive commands:"
    echo "  kubectl delete crd ${TRAEFIK_CRD_PROBLEMS[*]}"
    echo "You can re-run 'just traefik-crd-doctor' after apply and then 'just traefik-install' to recreate the CRDs."
    echo
    read -r -p "Proceed with these changes? [y/N]: " reply
    case "${reply}" in
        y|Y) ;;
        *) echo "Aborting without changes."; exit 1 ;;
    esac

    traefik_crd::apply_delete

    echo
    echo "Re-running diagnosis after apply..."
    traefik_crd::classify_all "${namespace}"
    traefik_crd::print_report "${namespace}" "${apply_flag}"

    if [ "${#TRAEFIK_CRD_PROBLEMS[@]}" -gt 0 ]; then
        exit 1
    fi

# Install Traefik as the cluster ingress using Helm.
# Run as a normal user (not root); ensures $HOME/.kube/config is readable by copying

# /etc/rancher/k3s/k3s.yaml if needed and uses it via KUBECONFIG for kubectl/helm.
traefik-install namespace='kube-system' version='':
    #!/usr/bin/env bash
    set -Eeuo pipefail

    if [ "$(id -u)" -eq 0 ] || [ -n "${SUDO_USER:-}" ]; then
        echo "ERROR: Do not run 'just traefik-install' with sudo." >&2
        echo "Run it as your normal user (e.g. pi) after kubeconfig is configured." >&2
        exit 1
    fi

    if [ -r "${HOME}/.kube/config" ]; then
        echo "User kubeconfig exists and is readable at ${HOME}/.kube/config."
    else
        if [ -f /etc/rancher/k3s/k3s.yaml ]; then
            echo "Creating a user kubeconfig from /etc/rancher/k3s/k3s.yaml..."
            sudo mkdir -p "${HOME}/.kube"
            sudo cp /etc/rancher/k3s/k3s.yaml "${HOME}/.kube/config"
            sudo chown -R "$(id -u):$(id -g)" "${HOME}/.kube"
            chmod 700 "${HOME}/.kube"
            chmod 600 "${HOME}/.kube/config"
        else
            echo "ERROR: No readable kubeconfig at ${HOME}/.kube/config." >&2
            echo "       /etc/rancher/k3s/k3s.yaml not found; install k3s or set up kubeconfig." >&2
            exit 1
        fi

        if ! kubectl version --client >/dev/null 2>&1; then
            echo "WARNING: kubectl client not found or not working." >&2
            echo "Helm may still fail if kubectl is missing." >&2
        fi
    fi

    export KUBECONFIG="${HOME}/.kube/config"

    if ! kubectl get nodes >/dev/null 2>&1; then
        echo "kubectl cannot reach the cluster (kubectl get nodes failed)." >&2
        echo "Check KUBECONFIG and k3s server status. Aborting Traefik install." >&2
        exit 1
    fi

    if ! command -v jq >/dev/null 2>&1; then
        echo "ERROR: 'jq' is required but not installed. Please install 'jq' and try again." >&2
        exit 1
    fi

    nodes_json=$(kubectl get nodes -o json)
    if echo "${nodes_json}" | jq -e '
        (.items | length > 0) and
        all(
          .items[];
          any(
            (.spec.taints // [])[]?;
            ((.key == "node-role.kubernetes.io/control-plane" or
              .key == "node-role.kubernetes.io/master") and
             .effect == "NoSchedule")
          )
        )
    ' >/dev/null; then
        echo "All nodes in this cluster are tainted as control-plane with NoSchedule and there are no" >&2
        echo "worker nodes. Traefik pods (which do not tolerate that taint by default) will remain" >&2
        echo "Pending and Helm will time out. For the dev ha3 topology, run 'just" >&2
        echo "ha3-untaint-control-plane' first to make the nodes schedulable, then re-run 'just" >&2
        echo "traefik-install'." >&2
        exit 1
    fi

    if ! command -v helm >/dev/null 2>&1; then
        echo "Helm is not installed. Run 'just helm-install' first" >&2
        echo "(see docs/raspi_cluster_operations.md), then re-run 'just traefik-install'." >&2
        exit 1
    fi

    helm repo add traefik https://traefik.github.io/charts --force-update
    helm repo update

    crd_lib="{{ justfile_directory() }}/scripts/lib/traefik_crd.sh"
    if [ ! -f "${crd_lib}" ]; then
        echo "ERROR: Traefik CRD helper script missing at ${crd_lib}." >&2
        exit 1
    fi

    # shellcheck disable=SC1090
    source "${crd_lib}"

    traefik_crd::classify_all "{{ namespace }}"
    traefik_crd::print_report "{{ namespace }}"

    if [ "${#TRAEFIK_CRD_PROBLEMS[@]}" -gt 0 ]; then
        echo "ERROR: Found existing Gateway API CRDs that are NOT owned by a Traefik Helm release in namespace '{{ namespace }}':" >&2
        echo "  ${TRAEFIK_CRD_PROBLEMS[*]}" >&2
        echo >&2
        traefik_crd::print_problem_details >&2
        echo >&2
        echo "Run 'just traefik-crd-doctor' for a detailed report and suggested kubectl commands." >&2
        exit 1
    fi

    if [ "${#TRAEFIK_CRD_PRESENT[@]}" -eq 0 ]; then
        echo "No existing Gateway API CRDs detected; Traefik will create them via the main chart."
    else
        echo "Existing Gateway API CRDs appear to be managed by a Traefik Helm release; proceeding with Helm install."
    fi

    helm_args=(
        upgrade --install traefik traefik/traefik
        --namespace "{{ namespace }}"
        --create-namespace
        --wait
        --timeout 5m
        --set service.type=ClusterIP
        --set experimental.kubernetesGateway.enabled=true
        --set providers.kubernetesGateway.enabled=true
        --set gateway.enabled=true
        --set gatewayClass.enabled=true
    )

    if [ -n "{{ version }}" ]; then
        helm_args+=(--version "{{ version }}")
    fi

    echo "Installing or upgrading Traefik via Helm in namespace '{{ namespace }}'..."
    if ! helm "${helm_args[@]}"; then
        echo "ERROR: Helm failed to install or upgrade the 'traefik' release in namespace '{{ namespace }}'." >&2
        echo "Helm status output:" >&2
        helm status traefik --namespace "{{ namespace }}" || echo "helm status failed" >&2
        if command -v kubectl >/dev/null 2>&1; then
            echo "Recent Traefik-related events (if any):" >&2
            kubectl -n "{{ namespace }}" get events --sort-by=.lastTimestamp \
                | grep -i traefik | tail -n 20 || true
        fi
        exit 1
    fi

    echo "Checking for Traefik Service 'traefik' in namespace '{{ namespace }}'..."
    if ! kubectl -n "{{ namespace }}" get svc traefik >/dev/null 2>&1; then
        echo "WARNING: Helm reports 'traefik' is deployed, but the Service 'traefik' was not found in namespace '{{ namespace }}'." >&2
        echo "Current Traefik-related Services in '{{ namespace }}':" >&2
        kubectl -n "{{ namespace }}" get svc | grep -i traefik || echo "  (none)" >&2
        echo "Current Traefik-related Deployments and Pods in '{{ namespace }}':" >&2
        kubectl -n "{{ namespace }}" get deploy,pods | grep -i traefik || echo "  (none)" >&2
        echo "You may need to inspect Helm status and pod logs for details:" >&2
        echo "  helm status traefik -n {{ namespace }}" >&2
        echo "  kubectl -n {{ namespace }} describe deploy traefik" >&2
        echo "  kubectl -n {{ namespace }} logs -l app.kubernetes.io/name=traefik" >&2
        exit 1
    fi

    echo "Traefik Service 'traefik' is present in namespace '{{ namespace }}'."

    traefik_crd::classify_all "{{ namespace }}"
    if [ "${#TRAEFIK_CRD_UNMANAGED[@]}" -gt 0 ]; then
        traefik_crd::adopt_unmanaged "{{ namespace }}" traefik
    fi

traefik-status namespace='kube-system':
    #!/usr/bin/env bash
    set -Eeuo pipefail

    export KUBECONFIG="${HOME}/.kube/config"

    kubectl -n "{{ namespace }}" get svc,po -l app.kubernetes.io/name=traefik

cf-tunnel-route host='':
    #!/usr/bin/env bash
    set -Eeuo pipefail

    if [ -z "{{ host }}" ]; then
        echo "Set host=<FQDN> (e.g., dspace-v3.example.com)." >&2
        exit 1
    fi

    svc_fqdn="traefik.kube-system.svc.cluster.local:80"

    printf '%s\n' \
        'Use the Cloudflare dashboard to create a route for:' \
        "  Hostname: {{ host }}" \
        "  Service URL: http://${svc_fqdn}" \
        '' \
        'Discover Traefik services:' \
        '  kubectl -n kube-system get svc -l app.kubernetes.io/name=traefik' \
        '' \
        'Dashboard steps are documented in docs/cloudflare_tunnel.md.'

_helm-oci-deploy release='' namespace='' chart='' values='' host='' version='' version_file='' tag='' default_tag='' allow_install='false' reuse_values='false':
    #!/usr/bin/env bash
    set -Eeuo pipefail

    export KUBECONFIG="${HOME}/.kube/config"

    allow_install="{{ allow_install }}"
    reuse_values="{{ reuse_values }}"

    raw_args=(
        "{{ release }}" "{{ namespace }}" "{{ chart }}" "{{ values }}" "{{ host }}" "{{ version }}"
        "{{ version_file }}" "{{ tag }}" "{{ default_tag }}"
    )

    release=""
    namespace=""
    chart=""
    values=""
    host=""
    version=""
    version_file=""
    tag=""
    default_tag=""

    assign_if_empty() {
        local var_name="${1}"
        local var_value="${2}"

        if [ -z "${!var_name}" ]; then
            printf -v "${var_name}" '%s' "${var_value}"
        fi
    }

    for raw_index in "${!raw_args[@]}"; do
        raw_arg="${raw_args[${raw_index}]}"

        if [ -z "${raw_arg}" ]; then
            continue
        fi

        case "${raw_arg}" in
            release=*) release="${raw_arg#release=}" ;;
            namespace=*) namespace="${raw_arg#namespace=}" ;;
            chart=*) chart="${raw_arg#chart=}" ;;
            values=*) values="${raw_arg#values=}" ;;
            host=*) host="${raw_arg#host=}" ;;
            version=*) version="${raw_arg#version=}" ;;
            version_file=*) version_file="${raw_arg#version_file=}" ;;
            tag=*) tag="${raw_arg#tag=}" ;;
            default_tag=*) default_tag="${raw_arg#default_tag=}" ;;
            *)
                case "${raw_index}" in
                    0) assign_if_empty release "${raw_arg}" ;;
                    1) assign_if_empty namespace "${raw_arg}" ;;
                    2) assign_if_empty chart "${raw_arg}" ;;
                    3) assign_if_empty values "${raw_arg}" ;;
                    4) assign_if_empty host "${raw_arg}" ;;
                    5) assign_if_empty version "${raw_arg}" ;;
                    6) assign_if_empty version_file "${raw_arg}" ;;
                    7) assign_if_empty tag "${raw_arg}" ;;
                    8) assign_if_empty default_tag "${raw_arg}" ;;
                esac
                ;;
        esac
    done

    strip_prefix() {
        local value="${1}"
        local key="${2}"
        local prefix="${key}="

        while [[ "${value}" == "${prefix}"* ]]; do
            value="${value#${prefix}}"
        done

        printf '%s' "${value}"
    }

    release="$(strip_prefix "${release}" release)"
    namespace="$(strip_prefix "${namespace}" namespace)"
    chart="$(strip_prefix "${chart}" chart)"
    values="$(strip_prefix "${values}" values)"
    host="$(strip_prefix "${host}" host)"
    version="$(strip_prefix "${version}" version)"
    version_file="$(strip_prefix "${version_file}" version_file)"
    tag="$(strip_prefix "${tag}" tag)"
    default_tag="$(strip_prefix "${default_tag}" default_tag)"

    if [ -z "${release}" ] || [ -z "${namespace}" ] || [ -z "${chart}" ]; then
        echo "Set release, namespace, and chart to deploy." >&2
        exit 1
    fi

    chart_version="${version}"
    if [ -z "${chart_version}" ] && [ -n "${version_file}" ] && [ -f "${version_file}" ]; then
        chart_version="$(
            sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' "${version_file}" | head -n1 | tr -d '[:space:]' || true
        )"
        if [ -z "${chart_version}" ]; then
            echo "Warning: version_file '${version_file}' did not contain a valid version" >&2
        fi
    fi

    version_args=()
    if [ -n "${chart_version}" ]; then
        version_args+=(--version "${chart_version}")
    fi

    value_args=()
    if [ -n "${values}" ]; then
        IFS=',' read -ra value_files <<< "${values}"
        for value_file in "${value_files[@]}"; do
            value_file="$(echo "${value_file}" | xargs)"
            if [ -n "${value_file}" ]; then
                value_args+=(-f "${value_file}")
            fi
        done
    fi

    image_tag="${tag}"
    if [ -z "${image_tag}" ] && [ -n "${default_tag}" ]; then
        image_tag="${default_tag}"
    fi

    set_args=()
    if [ -n "${host}" ]; then
        set_args+=(--set ingress.host="${host}")
    fi
    if [ -n "${image_tag}" ]; then
        set_args+=(--set image.tag="${image_tag}")
    fi

    if [[ "${chart}" == chart=* ]]; then
        echo "Internal bug: normalized chart still has leading 'chart=': '${chart}'" >&2
        exit 1
    fi

    helm_args=(upgrade "${release}" "${chart}" --namespace "${namespace}")

    if [ "${allow_install}" = "true" ]; then
        helm_args+=(--install --create-namespace)
    fi

    if [ "${reuse_values}" = "true" ]; then
        helm_args+=(--reuse-values)
    fi

    if [ ${#value_args[@]} -gt 0 ]; then
        helm_args+=("${value_args[@]}")
    fi

    if [ ${#set_args[@]} -gt 0 ]; then
        helm_args+=("${set_args[@]}")
    fi

    if [ ${#version_args[@]} -gt 0 ]; then
        helm_args+=("${version_args[@]}")
    fi

    helm "${helm_args[@]}"

helm-oci-install release='' namespace='' chart='' values='' host='' version='' version_file='' tag='' default_tag='':
    @just _helm-oci-deploy '{{ release }}' '{{ namespace }}' '{{ chart }}' '{{ values }}' '{{ host }}' '{{ version }}' '{{ version_file }}' '{{ tag }}' '{{ default_tag }}' allow_install='true' reuse_values='false'

helm-oci-upgrade release='' namespace='' chart='' values='' host='' version='' version_file='' tag='' default_tag='':
    @just _helm-oci-deploy '{{ release }}' '{{ namespace }}' '{{ chart }}' '{{ values }}' '{{ host }}' '{{ version }}' '{{ version_file }}' '{{ tag }}' '{{ default_tag }}' allow_install='false' reuse_values='true'

app-status namespace='' release='' host_key='ingress.host':
    #!/usr/bin/env bash
    set -Eeuo pipefail

    export KUBECONFIG="${HOME}/.kube/config"

    if [ -z "{{ namespace }}" ]; then
        echo "Set namespace to inspect." >&2
        exit 1
    fi

    if ! command -v kubectl >/dev/null 2>&1; then
        echo "kubectl is required to check the deployment." >&2
        exit 1
    fi

    kubectl -n "{{ namespace }}" get pods
    kubectl -n "{{ namespace }}" get ingress

    if [ -n "{{ release }}" ] && command -v helm >/dev/null 2>&1; then
        host="$(
            helm get values "{{ release }}" \
                --namespace "{{ namespace }}" \
                --all --output json 2>/dev/null |
                python3 - "{{ host_key }}" <<'PY'
                import json
                import sys

                try:
                    host_key = sys.argv[1]
                    data = json.load(sys.stdin)
                except (json.JSONDecodeError, KeyError, IndexError) as e:
                    sys.stderr.write(f"Error extracting host value: {e}\n")
                    sys.exit(1)
                except Exception as e:
                    sys.stderr.write(f"Unexpected error: {e}\n")
                    sys.exit(1)

                def get_with_dots(payload, dotted_key):
                    node = payload
                    for part in dotted_key.split('.'):
                        if not isinstance(node, dict):
                            return None
                        node = node.get(part)
                    return node

                if isinstance(data, dict):
                    host_value = get_with_dots(data, host_key)
                    if host_value:
                        print(host_value)
                PY
        )"
    else
        host=""
    fi

    if [ -n "${host}" ]; then
        printf 'Public URL: https://%s\n' "${host}"
    else
        echo "Public URL host not recorded; check the Helm release values."
    fi

wipe:
    #!/usr/bin/env bash
    set -euo pipefail

    sudo -E bash scripts/cleanup_mdns_publishers.sh
    sudo --preserve-env=SUGARKUBE_CLUSTER,SUGARKUBE_ENV,DRY_RUN,ALLOW_NON_ROOT bash scripts/wipe_node.sh

    scripts_dir="{{ justfile_directory() }}/scripts"
    if [ -x "${scripts_dir}/unset_doc_env_vars.sh" ]; then
        # shellcheck disable=SC1090
        source "${scripts_dir}/unset_doc_env_vars.sh"
    else
        printf 'WARNING: %s/unset_doc_env_vars.sh missing; environment variables not cleared.\n' "${scripts_dir}" >&2
    fi

scripts_dir := justfile_directory() + "/scripts"
image_dir := env_var_or_default("IMAGE_DIR", env_var("HOME") + "/sugarkube/images")
image_name := env_var_or_default("IMAGE_NAME", "sugarkube.img")
image_path := image_dir + "/" + image_name
install_cmd := env_var_or_default("INSTALL_CMD", scripts_dir + "/install_sugarkube_image.sh")
flash_cmd := env_var_or_default("FLASH_CMD", scripts_dir + "/flash_pi_media.sh")
flash_report_cmd := env_var_or_default("FLASH_REPORT_CMD", scripts_dir + "/flash_pi_media_report.py")
download_cmd := env_var_or_default("DOWNLOAD_CMD", scripts_dir + "/download_pi_image.sh")
download_args := env_var_or_default("DOWNLOAD_ARGS", "")
flash_args := env_var_or_default("FLASH_ARGS", "--assume-yes")
flash_report_args := env_var_or_default("FLASH_REPORT_ARGS", "")
flash_device := env_var_or_default("FLASH_DEVICE", "")
spot_check_cmd := env_var_or_default("SPOT_CHECK_CMD", scripts_dir + "/spot_check.sh")
spot_check_args := env_var_or_default("SPOT_CHECK_ARGS", "")
eeprom_cmd := env_var_or_default("EEPROM_CMD", scripts_dir + "/eeprom_nvme_first.sh")
boot_order_cmd := env_var_or_default("BOOT_ORDER_CMD", scripts_dir + "/boot_order.sh")
eeprom_args := env_var_or_default("EEPROM_ARGS", "")
clone_cmd := env_var_or_default("CLONE_CMD", scripts_dir + "/clone_to_nvme.sh")
clone_args := env_var_or_default("CLONE_ARGS", "")
clone_target := env_var_or_default("TARGET", "")
clone_wipe := env_var_or_default("WIPE", "0")
clean_mounts_cmd := env_var_or_default("CLEAN_MOUNTS_CMD", scripts_dir + "/cleanup_clone_mounts.sh")
preflight_cmd := env_var_or_default("PREFLIGHT_CMD", scripts_dir + "/preflight_clone.sh")
verify_clone_cmd := env_var_or_default("VERIFY_CLONE_CMD", scripts_dir + "/verify_clone.sh")
finalize_nvme_cmd := env_var_or_default("FINALIZE_NVME_CMD", scripts_dir + "/finalize_nvme.sh")
rollback_helper_cmd := env_var_or_default("ROLLBACK_HELPER_CMD", scripts_dir + "/rollback_to_sd_helper.sh")
validate_cmd := env_var_or_default("VALIDATE_CMD", scripts_dir + "/ssd_post_clone_validate.py")
validate_args := env_var_or_default("VALIDATE_ARGS", "")
post_clone_cmd := env_var_or_default("POST_CLONE_CMD", scripts_dir + "/post_clone_verify.sh")
post_clone_args := env_var_or_default("POST_CLONE_ARGS", "")
migrate_artifacts := env_var_or_default("MIGRATE_ARTIFACTS", justfile_directory() + "/artifacts/migrate-to-nvme")
migrate_skip_eeprom := env_var_or_default("SKIP_EEPROM", "0")
migrate_no_reboot := env_var_or_default("NO_REBOOT", "0")
qr_cmd := env_var_or_default("QR_CMD", justfile_directory() + "/scripts/generate_qr_codes.py")
qr_args := env_var_or_default("QR_ARGS", "")
health_cmd := env_var_or_default("HEALTH_CMD", justfile_directory() + "/scripts/ssd_health_monitor.py")
health_args := env_var_or_default("HEALTH_ARGS", "")
smoke_cmd := env_var_or_default("SMOKE_CMD", justfile_directory() + "/scripts/pi_smoke_test.py")
smoke_args := env_var_or_default("SMOKE_ARGS", "")
qemu_smoke_cmd := env_var_or_default("QEMU_SMOKE_CMD", justfile_directory() + "/scripts/qemu_pi_smoke_test.py")
qemu_smoke_args := env_var_or_default("QEMU_SMOKE_ARGS", "")
qemu_smoke_image := env_var_or_default("QEMU_SMOKE_IMAGE", "")
qemu_smoke_artifacts := env_var_or_default("QEMU_SMOKE_ARTIFACTS", justfile_directory() + "/artifacts/qemu-smoke")
support_bundle_cmd := env_var_or_default("SUPPORT_BUNDLE_CMD", justfile_directory() + "/scripts/collect_support_bundle.py")
support_bundle_args := env_var_or_default("SUPPORT_BUNDLE_ARGS", "")
support_bundle_host := env_var_or_default("SUPPORT_BUNDLE_HOST", "")
field_guide_cmd := env_var_or_default("FIELD_GUIDE_CMD", justfile_directory() + "/scripts/render_field_guide_pdf.py")
field_guide_args := env_var_or_default("FIELD_GUIDE_ARGS", "")
telemetry_cmd := env_var_or_default("TELEMETRY_CMD", justfile_directory() + "/scripts/publish_telemetry.py")
telemetry_args := env_var_or_default("TELEMETRY_ARGS", "")
teams_cmd := env_var_or_default("TEAMS_CMD", justfile_directory() + "/scripts/sugarkube_teams.py")
teams_args := env_var_or_default("TEAMS_ARGS", "")
workflow_notify_cmd := env_var_or_default("WORKFLOW_NOTIFY_CMD", justfile_directory() + "/scripts/workflow_artifact_notifier.py")
workflow_notify_args := env_var_or_default("WORKFLOW_NOTIFY_ARGS", "")
badge_cmd := env_var_or_default("BADGE_CMD", justfile_directory() + "/scripts/update_hardware_boot_badge.py")
badge_args := env_var_or_default("BADGE_ARGS", "")
rehearsal_cmd := env_var_or_default("REHEARSAL_CMD", justfile_directory() + "/scripts/pi_multi_node_join_rehearsal.py")
rehearsal_args := env_var_or_default("REHEARSAL_ARGS", "")
cluster_cmd := env_var_or_default("CLUSTER_CMD", justfile_directory() + "/scripts/pi_multi_node_join_rehearsal.py")
cluster_args := env_var_or_default("CLUSTER_ARGS", "")
cluster_bootstrap_args := env_var_or_default("CLUSTER_BOOTSTRAP_ARGS", "")
token_place_sample_cmd := env_var_or_default("TOKEN_PLACE_SAMPLE_CMD", justfile_directory() + "/scripts/token_place_replay_samples.py")
token_place_sample_args := env_var_or_default("TOKEN_PLACE_SAMPLE_ARGS", "--samples-dir " + justfile_directory() + "/samples/token_place")
mac_setup_cmd := env_var_or_default("MAC_SETUP_CMD", justfile_directory() + "/scripts/sugarkube_setup.py")
mac_setup_args := env_var_or_default("MAC_SETUP_ARGS", "")
start_here_args := env_var_or_default("START_HERE_ARGS", "")
sugarkube_cli := env_var_or_default("SUGARKUBE_CLI", justfile_directory() + "/scripts/sugarkube")
docs_verify_args := env_var_or_default("DOCS_VERIFY_ARGS", "")
simplify_docs_args := env_var_or_default("SIMPLIFY_DOCS_ARGS", "")
nvme_health_args := env_var_or_default("NVME_HEALTH_ARGS", "")

_default:
    @just default

help:
    @just --list

# Download the latest release or a specific asset into IMAGE_DIR

# Usage: just download-pi-image DOWNLOAD_ARGS="--release v1.2.3"
download-pi-image:
    "{{ download_cmd }}" --dir "{{ image_dir }}" {{ download_args }}

# Expand an image into IMAGE_PATH, downloading releases when missing

# Usage: just install-pi-image DOWNLOAD_ARGS="--release v1.2.3"
install-pi-image:
    "{{ install_cmd }}" --dir "{{ image_dir }}" --image "{{ image_path }}" {{ download_args }}

# Download (via install-pi-image) and flash to FLASH_DEVICE. Run with sudo.

# Usage: sudo just flash-pi FLASH_DEVICE=/dev/sdX
flash-pi: install-pi-image
    if [ -z "{{ flash_device }}" ]; then echo "Set FLASH_DEVICE to the target device (e.g. /dev/sdX) before running flash-pi." >&2; exit 1; fi
    "{{ flash_cmd }}" --image "{{ image_path }}" --device "{{ flash_device }}" {{ flash_args }}

# Download (via install-pi-image) and flash while generating Markdown/HTML reports.

# Usage: sudo just flash-pi-report FLASH_DEVICE=/dev/sdX FLASH_REPORT_ARGS="--cloud-init ~/user-data"
flash-pi-report: install-pi-image
    if [ -z "{{ flash_device }}" ]; then echo "Set FLASH_DEVICE to the target device (e.g. /dev/sdX) before running flash-pi-report." >&2; exit 1; fi
    "{{ flash_report_cmd }}" --image "{{ image_path }}" --device "{{ flash_device }}" {{ flash_args }} {{ flash_report_args }}

# Run the end-to-end readiness checks

# Usage: just doctor
doctor:
    "{{ justfile_directory() }}/scripts/sugarkube_doctor.sh"

# Surface the Start Here handbook in the terminal

# Usage: just start-here START_HERE_ARGS="--path-only"
start-here:
    "{{ sugarkube_cli }}" docs start-here {{ start_here_args }}

# Revert cmdline.txt and fstab entries back to the SD card defaults
# Usage: sudo just rollback-to-sd
# Run the Raspberry Pi spot check and capture artifacts

# Usage: sudo just spot-check
spot-check:
    "{{ spot_check_cmd }}" {{ spot_check_args }}

# Inspect or align the EEPROM boot order

# Usage: sudo just boot-order sd-nvme-usb
boot-order preset:
    "{{ boot_order_cmd }}" preset "{{ preset }}"

# Deprecated wrapper retained for one release; prefer `just boot-order nvme-first`

# Usage: sudo just eeprom-nvme-first
eeprom-nvme-first:
    @echo "[deprecated] 'just eeprom-nvme-first' will be removed in a future release." >&2
    @echo "[deprecated] Use 'just boot-order nvme-first' next time." >&2
    @echo "[deprecated] Applying BOOT_ORDER=0xF416 (NVMe → SD → USB → repeat)." >&2
    just --justfile "{{ justfile_directory() }}/justfile" boot-order nvme-first

# Clone the active SD card to the preferred NVMe/USB target

# Usage: sudo TARGET=/dev/nvme0n1 WIPE=1 just clone-ssd
clone-ssd:
    if [ -z "{{ clone_target }}" ]; then echo "Set TARGET to the destination device (e.g. /dev/nvme0n1) before running clone-ssd." >&2; exit 1; fi
    sudo --preserve-env=TARGET,WIPE,ALLOW_NON_ROOT,ALLOW_FAKE_BLOCK \
        "{{ clone_cmd }}" --target "{{ clone_target }}" {{ clone_args }}

show-disks:
    lsblk -e7 -o NAME,MAJ:MIN,SIZE,TYPE,FSTYPE,LABEL,UUID,PARTUUID,MOUNTPOINTS

preflight:
    if [ -z "{{ clone_target }}" ]; then echo "Set TARGET to the destination device (e.g. /dev/nvme0n1) before running preflight." >&2; exit 1; fi
    sudo --preserve-env=TARGET,WIPE \
    "{{ preflight_cmd }}"

verify-clone:
    if [ -z "{{ clone_target }}" ]; then echo "Set TARGET to the destination device (e.g. /dev/nvme0n1) before running verify-clone." >&2; exit 1; fi
    sudo --preserve-env=TARGET,MOUNT_BASE \
    env MOUNT_BASE={{ env_var_or_default("MOUNT_BASE", "/mnt/clone") }} \
    "{{ verify_clone_cmd }}"

finalize-nvme:
    sudo --preserve-env=EDITOR,FINALIZE_NVME_EDIT \
    "{{ finalize_nvme_cmd }}"

rollback-to-sd:
    "{{ rollback_helper_cmd }}"

# Clean up residual clone mounts and automounts.
# Usage:
#   just clean-mounts
#   TARGET=/dev/nvme1n1 MOUNT_BASE=/mnt/clone just clean-mounts
#   just clean-mounts -- --verbose --dry-run
#
# Notes:
# - Pass additional flags after `--`.
# - Defaults: TARGET=/dev/nvme0n1, MOUNT_BASE=/mnt/clone

clean-mounts args='':
    sudo --preserve-env=TARGET,MOUNT_BASE \
    env TARGET={{ env_var_or_default("TARGET", "/dev/nvme0n1") }} \
    MOUNT_BASE={{ env_var_or_default("MOUNT_BASE", "/mnt/clone") }} \
    "{{ clean_mounts_cmd }}" {{ args }}

clean-mounts-hard:
    sudo --preserve-env=TARGET,MOUNT_BASE \
    env TARGET={{ env_var_or_default("TARGET", "/dev/nvme0n1") }} \
    MOUNT_BASE={{ env_var_or_default("MOUNT_BASE", "/mnt/clone") }} \
    "{{ clean_mounts_cmd }}" --force

# One-command happy path: spot-check → EEPROM (optional) → clone → reboot

# Usage: sudo just migrate-to-nvme SKIP_EEPROM=1 NO_REBOOT=1
migrate-to-nvme:
    "{{ justfile_directory() }}/scripts/migrate_to_nvme.sh"

# Post-migration verification ensuring both partitions boot from NVMe

# Usage: sudo just post-clone-verify
post-clone-verify:
    "{{ post_clone_cmd }}" {{ post_clone_args }}

# Run post-clone validation against the active root filesystem

# Usage: sudo just validate-ssd-clone VALIDATE_ARGS="--stress-mb 256"
validate-ssd-clone:
    "{{ validate_cmd }}" {{ validate_args }}

# Collect SMART metrics and wear indicators for the active SSD

# Usage: sudo just monitor-ssd-health HEALTH_ARGS="--tag weekly"
monitor-ssd-health:
    "{{ health_cmd }}" {{ health_args }}

# Invoke the NVMe health helper shipped with the repository.
#

# Usage: sudo NVME_HEALTH_ARGS="--device /dev/nvme1n1" just nvme-health
nvme-health:
    command -v nvme >/dev/null 2>&1 || exit 0
    "{{ sugarkube_cli }}" nvme health {{ nvme_health_args }}

# Run pi_node_verifier remotely over SSH

# Usage: just smoke-test-pi SMOKE_ARGS="pi-a.local --reboot"
smoke-test-pi:
    "{{ smoke_cmd }}" {{ smoke_args }}

# Boot a built sugarkube image inside QEMU and collect first-boot reports

# Usage: sudo just qemu-smoke QEMU_SMOKE_IMAGE=deploy/sugarkube.img
qemu-smoke:
    if [ -z "{{ qemu_smoke_image }}" ]; then echo "Set QEMU_SMOKE_IMAGE to the built image (sugarkube.img or .img.xz)." >&2; exit 1; fi
    sudo "{{ qemu_smoke_cmd }}" --image "{{ qemu_smoke_image }}" --artifacts-dir "{{ qemu_smoke_artifacts }}" {{ qemu_smoke_args }}

# Render the printable Pi carrier field guide PDF

# Usage: just field-guide FIELD_GUIDE_ARGS="--wrap 70"
field-guide:
    "{{ field_guide_cmd }}" {{ field_guide_args }}

# Publish anonymized telemetry payloads once.
publish-telemetry:
    "{{ telemetry_cmd }}" {{ telemetry_args }}

# Send a manual Slack/Matrix notification using sugarkube-teams
notify-teams:
    "{{ teams_cmd }}" {{ teams_args }}

# Watch a workflow run and raise desktop notifications when artifacts are ready

# Usage: just notify-workflow WORKFLOW_NOTIFY_ARGS="--run-url https://github.com/..."
notify-workflow:
    "{{ workflow_notify_cmd }}" {{ workflow_notify_args }}

# Update the hardware boot conformance badge JSON

# Usage: just update-hardware-badge BADGE_ARGS="--status warn --notes 'pi-b'"
update-hardware-badge:
    "{{ badge_cmd }}" {{ badge_args }}

# Run multi-node join rehearsals against control-plane and candidate agents

# Usage: just rehearse-join REHEARSAL_ARGS="controller.local --agents pi-a.local"
rehearse-join:
    "{{ rehearsal_cmd }}" {{ rehearsal_args }}

# Apply the k3s join command to each agent and optionally wait for readiness

# Usage: just cluster-up CLUSTER_ARGS="control.local --agents worker-a worker-b --apply --apply-wait"
cluster-up:
    "{{ cluster_cmd }}" {{ cluster_args }}

# Usage: just cluster-bootstrap CLUSTER_BOOTSTRAP_ARGS="--config cluster.toml"
cluster-bootstrap:
    "{{ sugarkube_cli }}" pi cluster {{ cluster_bootstrap_args }}

# Install CLI dependencies inside GitHub Codespaces or fresh containers

# Usage: just codespaces-bootstrap
codespaces-bootstrap:
    sudo apt-get update
    sudo apt-get install -y \
    aspell \
    aspell-en \
    curl \
    gh \
    jq \
    pv \
    python3 \
    python3-pip \
    python3-venv \
    unzip \
    xz-utils
    python3 -m pip install --user --upgrade pip pre-commit pyspelling linkchecker

# Run spellcheck and linkcheck to keep docs automation aligned

# Usage: just docs-verify
docs-verify:
    "{{ sugarkube_cli }}" docs verify {{ docs_verify_args }}

# Install documentation prerequisites and run spell/link checks without touching

# code linters. Usage: just simplify-docs (forwards to sugarkube docs simplify)
simplify-docs:
    "{{ sugarkube_cli }}" docs simplify {{ simplify_docs_args }}

# Generate printable QR codes that link to the quickstart and troubleshooting docs

# Usage: just qr-codes QR_ARGS="--output-dir ~/qr"
qr-codes:
    "{{ qr_cmd }}" {{ qr_args }}

# Replay bundled token.place sample payloads and write reports

# Usage: just token-place-samples TOKEN_PLACE_SAMPLE_ARGS="--dry-run"
token-place-samples:
    "{{ sugarkube_cli }}" token-place samples {{ token_place_sample_args }}

# Run the macOS setup wizard to install brew formulas and scaffold directories

# Usage: just mac-setup MAC_SETUP_ARGS="--apply"
mac-setup:
    "{{ mac_setup_cmd }}" {{ mac_setup_args }}

# Collect Kubernetes, systemd, and compose diagnostics from a running Pi

# Usage: just support-bundle SUPPORT_BUNDLE_HOST=pi.local
support-bundle:
    if [ -z "{{ support_bundle_host }}" ]; then echo "Set SUPPORT_BUNDLE_HOST to the target host before running support-bundle." >&2; exit 1; fi
    "{{ support_bundle_cmd }}" "{{ support_bundle_host }}" {{ support_bundle_args }}

# Bootstrap Flux controllers and sync manifests for an environment
flux-bootstrap env='dev':
    "{{ scripts_dir }}/flux-bootstrap.sh" "{{ env }}"

# Reconcile the platform Kustomization via Flux
platform-apply env='dev':
    flux reconcile kustomization platform \
    --namespace flux-system \
    --with-source

# Reseal SOPS secrets for an environment
seal-secrets env='dev':
    "{{ scripts_dir }}/seal-secrets.sh" "{{ env }}"

# Backwards-compatible alias that calls flux-bootstrap
platform-bootstrap env='dev':
    just flux-bootstrap env={{ env }}
