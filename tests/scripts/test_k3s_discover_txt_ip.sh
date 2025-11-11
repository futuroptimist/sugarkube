#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DISCOVER_SCRIPT="${REPO_ROOT}/scripts/k3s-discover.sh"

TMP_DIR="$(mktemp -d)"

BIN_DIR="${TMP_DIR}/bin"
mkdir -p "${BIN_DIR}" "${TMP_DIR}/avahi" "${TMP_DIR}/run"

API_READY_LOG="${TMP_DIR}/api-ready.log"
INSTALL_LOG="${TMP_DIR}/install-env.log"
AVAHI_LOG="${TMP_DIR}/avahi-browse.log"

cat >"${BIN_DIR}/sleep" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${BIN_DIR}/sleep"

cat >"${BIN_DIR}/systemctl" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${BIN_DIR}/systemctl"

cat >"${BIN_DIR}/iptables" <<'SH'
#!/usr/bin/env bash
if [ "${1:-}" = "-V" ] || [ "${1:-}" = "--version" ]; then
  echo "iptables v1.8.9 (nf_tables)"
  exit 0
fi
exit 0
SH
chmod +x "${BIN_DIR}/iptables"

cat >"${BIN_DIR}/ip6tables" <<'SH'
#!/usr/bin/env bash
if [ "${1:-}" = "-V" ] || [ "${1:-}" = "--version" ]; then
  echo "ip6tables v1.8.9 (nf_tables)"
  exit 0
fi
exit 0
SH
chmod +x "${BIN_DIR}/ip6tables"

cat >"${BIN_DIR}/apt-get" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${BIN_DIR}/apt-get"

cat >"${BIN_DIR}/l4_probe.sh" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${BIN_DIR}/l4_probe.sh"

cat >"${BIN_DIR}/check_time_sync.sh" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${BIN_DIR}/check_time_sync.sh"

cat >"${BIN_DIR}/check_apiready.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'ts=%s event=apiready outcome=ok host=%s port=%s\n' \
  "$(date -Is 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S')" \
  "${SERVER_HOST:-}" \
  "${SERVER_PORT:-}" >> "${API_READY_LOG}"
exit 0
SH
chmod +x "${BIN_DIR}/check_apiready.sh"

cat >"${BIN_DIR}/getent" <<'SH'
#!/usr/bin/env bash
exit 2
SH
chmod +x "${BIN_DIR}/getent"

cat >"${BIN_DIR}/avahi-browse" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${AVAHI_LOG}"
cat <<'OUT'
=;eth0;IPv4;k3s-sugar-dev@sugarkube0.local (server);_k3s-sugar-dev._tcp;local;sugarkube0.local;198.51.100.5;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;txt=phase=ready;txt=ip4=198.51.100.10;txt=ip6=2001:db8::10;txt=host=sugarkube0.local
OUT
exit 0
SH
chmod +x "${BIN_DIR}/avahi-browse"

cat >"${BIN_DIR}/avahi-publish" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${BIN_DIR}/avahi-publish"

cat >"${BIN_DIR}/avahi-publish-service" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${BIN_DIR}/avahi-publish-service"

cat >"${BIN_DIR}/avahi-resolve-host-name" <<'SH'
#!/usr/bin/env bash
exit 1
SH
chmod +x "${BIN_DIR}/avahi-resolve-host-name"

cat >"${BIN_DIR}/journalctl" <<'SH'
#!/usr/bin/env bash
exit 1
SH
chmod +x "${BIN_DIR}/journalctl"

cat >"${BIN_DIR}/server-parity.sh" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${BIN_DIR}/server-parity.sh"

cat >"${BIN_DIR}/elect-leader.sh" <<'SH'
#!/usr/bin/env bash
cat <<'OUT'
winner=no
key=testkey
OUT
exit 0
SH
chmod +x "${BIN_DIR}/elect-leader.sh"

cat >"${BIN_DIR}/k3s-install-stub.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
{
  echo "ARGS:$*"
  echo "K3S_URL=${K3S_URL:-}"
  echo "SERVER_IP=${SERVER_IP:-}"
} >> "${INSTALL_LOG}"
exit 0
SH
chmod +x "${BIN_DIR}/k3s-install-stub.sh"

PATH="${BIN_DIR}:${PATH}"
export PATH

export SUGARKUBE_K3S_INSTALL_SCRIPT="${BIN_DIR}/k3s-install-stub.sh"
export SUGARKUBE_SKIP_MDNS_SELF_CHECK=1
export SUGARKUBE_CLUSTER=sugar
export SUGARKUBE_ENV=dev
export SUGARKUBE_ALLOW_NON_ROOT=1
export ALLOW_NON_ROOT=1
export SUGARKUBE_SUDO_BIN=""
export SUGARKUBE_SKIP_SYSTEMCTL=1
export SUGARKUBE_MDNS_DBUS=0
export SUGARKUBE_SERVERS=2
export SUGARKUBE_AVAHI_SERVICE_DIR="${TMP_DIR}/avahi"
export SUGARKUBE_API_READY_CHECK_BIN="${BIN_DIR}/check_apiready.sh"
export SUGARKUBE_L4_PROBE_BIN="${BIN_DIR}/l4_probe.sh"
export SUGARKUBE_TIME_SYNC_BIN="${BIN_DIR}/check_time_sync.sh"
export SUGARKUBE_SERVER_FLAG_PARITY_BIN="${BIN_DIR}/server-parity.sh"
export SUGARKUBE_ELECT_LEADER_BIN="${BIN_DIR}/elect-leader.sh"
export SUGARKUBE_DISABLE_JOIN_GATE=1
export SUGARKUBE_RUNTIME_DIR="${TMP_DIR}/run"
export SUGARKUBE_ALLOW_TOKEN_CREATE=1
TOKEN_VAR="SUGARKUBE_TOKEN"
export "${TOKEN_VAR}=test-token"
export INSTALL_LOG
export API_READY_LOG
export AVAHI_LOG
export DISCOVERY_ATTEMPTS=1

set +e
command_output="$(timeout 60 bash "${DISCOVER_SCRIPT}" 2>&1)"
status=$?
set -e

INSTALL_LOG_COPY="$(mktemp)"
API_READY_LOG_COPY="$(mktemp)"
if [ -f "${INSTALL_LOG}" ]; then
  cp "${INSTALL_LOG}" "${INSTALL_LOG_COPY}"
else
  : >"${INSTALL_LOG_COPY}"
fi
if [ -f "${API_READY_LOG}" ]; then
  cp "${API_READY_LOG}" "${API_READY_LOG_COPY}"
else
  : >"${API_READY_LOG_COPY}"
fi
trap 'rm -rf "${TMP_DIR}" "${INSTALL_LOG_COPY}" "${API_READY_LOG_COPY}"' EXIT

if [ "${status}" -eq 124 ]; then
  echo "k3s-discover.sh timed out" >&2
  printf '%s\n' "${command_output}" >&2
  exit 1
fi

if [ "${status}" -ne 0 ]; then
  printf '%s\n' "${command_output}" >&2
  echo "k3s-discover.sh exited with ${status}" >&2
  exit 1
fi

if ! grep -q 'accept_path=txt' <<<"${command_output}"; then
  echo "accept_path txt log missing" >&2
  exit 1
fi

if ! grep -q 'txt_ip=1' <<<"${command_output}"; then
  echo "txt_ip flag missing" >&2
  exit 1
fi

if ! grep -q 'txt_ip_source=ip4' <<<"${command_output}"; then
  echo "txt_ip_source log missing" >&2
  exit 1
fi

if [ ! -s "${API_READY_LOG_COPY}" ]; then
  echo "API readiness helper not invoked" >&2
  exit 1
fi

if ! grep -q 'K3S_URL=https://sugarkube0.local:6443' "${INSTALL_LOG_COPY}"; then
  echo "K3S_URL was not configured with hostname" >&2
  exit 1
fi

if ! grep -q 'SERVER_IP=198.51.100.10' "${INSTALL_LOG_COPY}"; then
  echo "SERVER_IP did not capture TXT address" >&2
  exit 1
fi
