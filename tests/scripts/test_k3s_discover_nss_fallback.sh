#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DISCOVER_SCRIPT="${REPO_ROOT}/scripts/k3s-discover.sh"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

BIN_DIR="${TMP_DIR}/bin"
mkdir -p "${BIN_DIR}" "${TMP_DIR}/avahi"

AVAHI_LOG="${TMP_DIR}/avahi-browse.log"
RESOLVE_LOG="${TMP_DIR}/avahi-resolve.log"
GETENT_LOG="${TMP_DIR}/getent.log"
API_READY_LOG="${TMP_DIR}/api-ready.log"
INSTALL_LOG="${TMP_DIR}/install.log"


real_getent="$(command -v getent || true)"
real_ip="$(command -v ip || true)"
export AVAHI_LOG RESOLVE_LOG GETENT_LOG API_READY_LOG INSTALL_LOG
export real_getent real_ip

cat >"${TMP_DIR}/mdns.txt" <<'EOF'
=;eth0;IPv4;k3s API sugar/dev [server] on sugarkube0.local;_k3s-sugar-dev._tcp;local;sugarkube0.local;;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;txt=mode=alive
EOF

cat >"${BIN_DIR}/gdbus" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
chmod +x "${BIN_DIR}/gdbus"

cat >"${BIN_DIR}/systemctl" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  is-active)
    exit 0
    ;;
  restart|reload)
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
STUB
chmod +x "${BIN_DIR}/systemctl"

cat >"${BIN_DIR}/busctl" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
exit 1
STUB
chmod +x "${BIN_DIR}/busctl"

cat >"${BIN_DIR}/avahi-browse" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
echo "=;eth0;IPv4;k3s API sugar/dev [server] on sugarkube0.local;_k3s-sugar-dev._tcp;local;sugarkube0.local;;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;txt=mode=alive" | tee -a "${AVAHI_LOG}" >/dev/null
echo "=;eth0;IPv4;k3s API sugar/dev [server] on sugarkube0.local;_k3s-sugar-dev._tcp;local;sugarkube0.local;;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;txt=mode=alive"
exit 0
STUB
chmod +x "${BIN_DIR}/avahi-browse"

cat >"${BIN_DIR}/avahi-resolve" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
echo "avahi-resolve:$*" >> "${RESOLVE_LOG}"
exit 2
STUB
chmod +x "${BIN_DIR}/avahi-resolve"

cat >"${BIN_DIR}/getent" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
echo "getent:$*" >> "${GETENT_LOG}"
case "${1:-}" in
  hosts|ahostsv4)
    if [ "${2:-}" = "sugarkube0.local" ]; then
      echo "192.0.2.50 sugarkube0.local"
      exit 0
    fi
    ;;
  ahostsv6)
    if [ "${2:-}" = "sugarkube0.local" ]; then
      echo "2001:db8::50 STREAM sugarkube0.local"
      exit 0
    fi
    ;;
esac
if [ -n "${real_getent}" ]; then
  exec "${real_getent}" "$@"
fi
exit 2
STUB
chmod +x "${BIN_DIR}/getent"

cat >"${BIN_DIR}/ip" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "-4" ] && [ "${2:-}" = "-o" ] && [ "${3:-}" = "addr" ] && [ "${4:-}" = "show" ]; then
  echo "2: eth0    inet 192.0.2.10/24 brd 192.0.2.255 scope global eth0"
  exit 0
fi
if [ -n "${real_ip}" ]; then
  exec "${real_ip}" "$@"
fi
echo "unsupported ip args: $*" >&2
exit 1
STUB
chmod +x "${BIN_DIR}/ip"

for cmd in iptables ip6tables apt-get avahi-publish-service avahi-publish; do
  cat >"${BIN_DIR}/${cmd}" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
exit 0
STUB
  chmod +x "${BIN_DIR}/${cmd}"
done

cat >"${BIN_DIR}/sleep" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
chmod +x "${BIN_DIR}/sleep"

cat >"${TMP_DIR}/api-ready.sh" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
printf 'SERVER_HOST=%s SERVER_IP=%s\n' "${SERVER_HOST:-}" "${SERVER_IP:-}" >> "${API_READY_LOG}"
exit 0
STUB
chmod +x "${TMP_DIR}/api-ready.sh"

cat >"${TMP_DIR}/mdns-selfcheck.sh" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
chmod +x "${TMP_DIR}/mdns-selfcheck.sh"

cat >"${TMP_DIR}/l4-probe.sh" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
chmod +x "${TMP_DIR}/l4-probe.sh"

cat >"${TMP_DIR}/time-sync.sh" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
chmod +x "${TMP_DIR}/time-sync.sh"

cat >"${TMP_DIR}/parity-check.sh" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
chmod +x "${TMP_DIR}/parity-check.sh"

cat >"${TMP_DIR}/install-k3s.sh" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "${K3S_URL:-}" >> "${INSTALL_LOG}"
exit 0
STUB
chmod +x "${TMP_DIR}/install-k3s.sh"

cat >"${TMP_DIR}/join-gate.sh" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  wait|acquire|release)
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
STUB
chmod +x "${TMP_DIR}/join-gate.sh"

cat >"${TMP_DIR}/configure-avahi.sh" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
exit 0
STUB
chmod +x "${TMP_DIR}/configure-avahi.sh"

export PATH="${BIN_DIR}:${PATH}"
export ALLOW_NON_ROOT=1
export SUGARKUBE_SKIP_SYSTEMCTL=1
export SUGARKUBE_SKIP_MDNS_SELF_CHECK=1
export SUGARKUBE_CLUSTER="sugar"
export SUGARKUBE_ENV="dev"
export SUGARKUBE_SERVERS=2
export SUGARKUBE_TOKEN="$(printf "dummy")"
export SUGARKUBE_AVAHI_SERVICE_DIR="${TMP_DIR}/avahi"
export SUGARKUBE_API_READY_CHECK_BIN="${TMP_DIR}/api-ready.sh"
export SUGARKUBE_MDNS_SELF_CHECK_BIN="${TMP_DIR}/mdns-selfcheck.sh"
export SUGARKUBE_L4_PROBE_BIN="${TMP_DIR}/l4-probe.sh"
export SUGARKUBE_TIME_SYNC_BIN="${TMP_DIR}/time-sync.sh"
export SUGARKUBE_SERVER_FLAG_PARITY_BIN="${TMP_DIR}/parity-check.sh"
export SUGARKUBE_K3S_INSTALL_SCRIPT="${TMP_DIR}/install-k3s.sh"
export SUGARKUBE_JOIN_GATE_BIN="${TMP_DIR}/join-gate.sh"
export SUGARKUBE_CONFIGURE_AVAHI_BIN="${TMP_DIR}/configure-avahi.sh"
export SUGARKUBE_TEST_SKIP_PUBLISH_SLEEP=1
export SUGARKUBE_MDNS_BOOT_RETRIES=1
export SUGARKUBE_MDNS_BOOT_DELAY=0
export SUGARKUBE_MDNS_SERVER_RETRIES=1
export SUGARKUBE_MDNS_SERVER_DELAY=0
export DISCOVERY_ATTEMPTS=1
export DISCOVERY_WAIT_SECS=0
export SUGARKUBE_STRICT_IPTABLES=0
export HOSTNAME="sugarkube1.local"
export SUGARKUBE_MDNS_ABSENCE_GATE=0
export SUGARKUBE_MDNS_FIXTURE_FILE="${TMP_DIR}/mdns.txt"

set +e
discover_log="${TMP_DIR}/discover.log"
COMMAND_TIMEOUT=20 DISCOVER_LOG="${discover_log}" python3 - "${DISCOVER_SCRIPT}" <<'PY'
import os
import subprocess
import sys

script = sys.argv[1]
log_path = os.environ["DISCOVER_LOG"]
with open(log_path, "w", encoding="utf-8") as handle:
    proc = subprocess.Popen(
        [script],
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        code = proc.wait(timeout=float(os.environ.get("COMMAND_TIMEOUT", "20")))
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        code = 124
    sys.exit(code)
PY
status=$?
set -e

command_output="$(cat "${discover_log}" 2>/dev/null)"
if [ "${status}" -ne 0 ]; then
  printf '%s\n' "${command_output}" >&2
  echo "k3s-discover.sh exited with ${status}" >&2
  exit 1
fi

if ! grep -q 'accept_path=nss' <<<"${command_output}"; then
  printf '%s\n' "${command_output}" >&2
  echo "expected nss accept log missing" >&2
  exit 1
fi

if ! grep -q 'browse_ok=1' <<<"${command_output}"; then
  printf '%s\n' "${command_output}" >&2
  echo "expected browse_ok log missing" >&2
  exit 1
fi

if ! grep -q 'nss_ok=1' <<<"${command_output}"; then
  printf '%s\n' "${command_output}" >&2
  echo "expected nss_ok log missing" >&2
  exit 1
fi

if ! grep -q 'mode=alive' <<<"${command_output}"; then
  printf '%s\n' "${command_output}" >&2
  echo "expected mode field missing" >&2
  exit 1
fi

if [ ! -s "${API_READY_LOG}" ]; then
  printf '%s\n' "${command_output}" >&2
  echo "API readiness helper was not invoked" >&2
  exit 1
fi

if ! grep -q 'SERVER_HOST=sugarkube0.local' "${API_READY_LOG}"; then
  cat "${API_READY_LOG}" >&2
  echo "SERVER_HOST was not passed to API check" >&2
  exit 1
fi

if ! grep -q 'SERVER_IP=192.0.2.50' "${API_READY_LOG}"; then
  cat "${API_READY_LOG}" >&2
  echo "SERVER_IP was not passed to API check" >&2
  exit 1
fi

if [ ! -s "${INSTALL_LOG}" ]; then
  printf '%s\n' "${command_output}" >&2
  echo "k3s install stub was not invoked" >&2
  exit 1
fi

if ! grep -q 'https://sugarkube0.local:6443' "${INSTALL_LOG}"; then
  cat "${INSTALL_LOG}" >&2
  echo "expected K3S_URL not recorded" >&2
  exit 1
fi

if [ ! -s "${RESOLVE_LOG}" ]; then
  printf '%s\n' "${command_output}" >&2
  echo "avahi-resolve stub was not called" >&2
  exit 1
fi

