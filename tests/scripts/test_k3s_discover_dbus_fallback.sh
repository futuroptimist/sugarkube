#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DISCOVER_SCRIPT="${REPO_ROOT}/scripts/k3s-discover.sh"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

BIN_DIR="${TMP_DIR}/bin"
mkdir -p "${BIN_DIR}"

BUSCTL_LOG="${TMP_DIR}/busctl.log"
API_READY_LOG="${TMP_DIR}/api-ready.log"
AVAHI_LOG="${TMP_DIR}/avahi-browse.log"
RESOLVE_LOG="${TMP_DIR}/avahi-resolve.log"
GETENT_LOG="${TMP_DIR}/getent.log"
INSTALL_LOG="${TMP_DIR}/install.log"
export BUSCTL_LOG API_READY_LOG AVAHI_LOG RESOLVE_LOG GETENT_LOG INSTALL_LOG

real_ip_bin="$(command -v ip || true)"
real_getent_bin="$(command -v getent || true)"

cat >"${BIN_DIR}/gdbus" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${BIN_DIR}/gdbus"

cat >"${BIN_DIR}/systemctl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
command="${1:-}"
case "${command}" in
  is-active)
    shift
    if [ "${1:-}" = "--quiet" ]; then
      shift
    fi
    echo "active"
    exit 0
    ;;
  restart|reload)
    exit 0
    ;;
esac
exit 0
SH
chmod +x "${BIN_DIR}/systemctl"

cat >"${BIN_DIR}/busctl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
echo "busctl:$*" >> "${BUSCTL_LOG}"
echo "Call failed: Method GetVersionString unavailable" >&2
exit 1
SH
chmod +x "${BIN_DIR}/busctl"

cat >"${BIN_DIR}/avahi-browse" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
record="=;eth0;IPv4;k3s API sugar/dev [server] on sugarkube0.local;_k3s-sugar-dev._tcp;local;sugarkube0.local;;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;txt=mode=alive"
echo "${record}" >> "${AVAHI_LOG}"
echo "${record}"
exit 0
SH
chmod +x "${BIN_DIR}/avahi-browse"

cat >"${BIN_DIR}/avahi-resolve" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
echo "avahi-resolve:$*" >> "${RESOLVE_LOG}"
exit 2
SH
chmod +x "${BIN_DIR}/avahi-resolve"

cat >"${BIN_DIR}/getent" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
echo "getent:$*" >> "${GETENT_LOG}"
case "${1:-}" in
  hosts|ahostsv4)
    if [ "${2:-}" = "sugarkube0.local" ]; then
      echo "198.51.100.25 sugarkube0.local"
      exit 0
    fi
    ;;
  ahostsv6)
    if [ "${2:-}" = "sugarkube0.local" ]; then
      echo "2001:db8::25 STREAM sugarkube0.local"
      exit 0
    fi
    ;;
esac
if [ -n "${real_getent_bin}" ]; then
  exec "${real_getent_bin}" "$@"
fi
exit 2
SH
chmod +x "${BIN_DIR}/getent"

cat >"${BIN_DIR}/ip" <<SH
#!/usr/bin/env bash
set -eo pipefail
if [ "\$#" -ge 4 ] && [ "\$1" = "-4" ] && [ "\$2" = "-o" ] && [ "\$3" = "addr" ] && [ "\$4" = "show" ]; then
  echo "2: eth0    inet 192.0.2.10/24 brd 192.0.2.255 scope global eth0"
  exit 0
fi
if [ -n "${real_ip_bin}" ]; then
  exec "${real_ip_bin}" "\$@"
fi
echo "unsupported ip args: \$*" >&2
exit 1
SH
chmod +x "${BIN_DIR}/ip"

for cmd in iptables ip6tables apt-get avahi-publish-service avahi-publish; do
  cat >"${BIN_DIR}/${cmd}" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
exit 0
SH
  chmod +x "${BIN_DIR}/${cmd}"
done

cat >"${BIN_DIR}/sleep" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${BIN_DIR}/sleep"

cat >"${TMP_DIR}/l4-probe.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
exit 0
SH
chmod +x "${TMP_DIR}/l4-probe.sh"

cat >"${TMP_DIR}/time-sync.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
exit 0
SH
chmod +x "${TMP_DIR}/time-sync.sh"

cat >"${TMP_DIR}/parity-check.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
exit 0
SH
chmod +x "${TMP_DIR}/parity-check.sh"

cat >"${TMP_DIR}/install-k3s.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "${K3S_URL:-}" >> "${INSTALL_LOG}"
exit 0
SH
chmod +x "${TMP_DIR}/install-k3s.sh"

cat >"${TMP_DIR}/join-gate.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  wait|acquire|release)
    exit 0
    ;;
esac
exit 0
SH
chmod +x "${TMP_DIR}/join-gate.sh"

cat >"${TMP_DIR}/configure-avahi.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
exit 0
SH
chmod +x "${TMP_DIR}/configure-avahi.sh"

cat >"${TMP_DIR}/api-ready.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
timestamp="$(date -Is 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S')"
printf 'ts=%s event=apiready outcome=ok attempts=1 elapsed=0 status=401 host=%s port=%s mode=http\n' \
  "${timestamp}" \
  "${SERVER_HOST:-}" \
  "${SERVER_PORT:-}" | tee -a "${API_READY_LOG}" >/dev/null
printf 'SERVER_HOST=%s SERVER_IP=%s\n' "${SERVER_HOST:-}" "${SERVER_IP:-}" >> "${API_READY_LOG}"
exit 0
SH
chmod +x "${TMP_DIR}/api-ready.sh"

cat >"${TMP_DIR}/mdns-selfcheck.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'ts=%s event=mdns_selfcheck outcome=confirmed role=%s host=%s phase=%s check=stub\n' \
  "$(date -Is 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S')" \
  "${ROLE:-stub}" \
  "${MDNS_HOST_RAW:-${HOSTNAME:-stub}}" \
  "${PHASE:-stub}" >/dev/null
exit 0
SH
chmod +x "${TMP_DIR}/mdns-selfcheck.sh"

export PATH="${BIN_DIR}:${PATH}"
export ALLOW_NON_ROOT=1
export SUGARKUBE_SKIP_SYSTEMCTL=1
export SUGARKUBE_SKIP_MDNS_SELF_CHECK=1
export SUGARKUBE_CLUSTER="sugar"
export SUGARKUBE_ENV="dev"
export SUGARKUBE_MDNS_HOST="cube.local"
export SUGARKUBE_AVAHI_SERVICE_DIR="${TMP_DIR}/avahi"
export SUGARKUBE_API_READY_CHECK_BIN="${TMP_DIR}/api-ready.sh"
export SUGARKUBE_MDNS_BOOT_RETRIES=1
export SUGARKUBE_MDNS_BOOT_DELAY=0
export SUGARKUBE_MDNS_SERVER_RETRIES=1
export SUGARKUBE_MDNS_SERVER_DELAY=0
export SUGARKUBE_MDNS_DBUS=1
export SUGARKUBE_MDNS_SELF_CHECK_BIN="${TMP_DIR}/mdns-selfcheck.sh"
export SUGARKUBE_TEST_SKIP_PUBLISH_SLEEP=1
export SUGARKUBE_L4_PROBE_BIN="${TMP_DIR}/l4-probe.sh"
export SUGARKUBE_TIME_SYNC_BIN="${TMP_DIR}/time-sync.sh"
export SUGARKUBE_SERVER_FLAG_PARITY_BIN="${TMP_DIR}/parity-check.sh"
export SUGARKUBE_K3S_INSTALL_SCRIPT="${TMP_DIR}/install-k3s.sh"
export SUGARKUBE_JOIN_GATE_BIN="${TMP_DIR}/join-gate.sh"
export SUGARKUBE_CONFIGURE_AVAHI_BIN="${TMP_DIR}/configure-avahi.sh"
export SUGARKUBE_STRICT_IPTABLES=0
export SUGARKUBE_MDNS_ABSENCE_GATE=0
export HOSTNAME="cube.local"

start_ts="$(python3 - <<'PY'
import time
print(repr(time.time()))
PY
)"

set +e
discover_log="${TMP_DIR}/discover.log"
COMMAND_TIMEOUT=12 DISCOVER_LOG="${discover_log}" python3 - "${DISCOVER_SCRIPT}" <<'PY'
import os
import subprocess
import sys

script = sys.argv[1]
log_path = os.environ.get("DISCOVER_LOG", "")
timeout = float(os.environ.get("COMMAND_TIMEOUT", "12"))

if not log_path:
    raise SystemExit(2)

with open(log_path, "w", encoding="utf-8") as handle:
    proc = subprocess.Popen(
        [script, "--test-mdns-fallback"],
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        return_code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        return_code = 124
    sys.exit(return_code)
PY
status=$?
command_output="$(cat "${discover_log}" 2>/dev/null)"
set -e

if [ "${status}" -ne 0 ]; then
  printf '%s\n' "${command_output}" >&2
  echo "k3s-discover.sh exited with ${status}" >&2
  exit 1
fi

end_ts="$(python3 - <<'PY'
import time
print(repr(time.time()))
PY
)"

elapsed_data="$(python3 - <<PY
start = float(${start_ts})
end = float(${end_ts})
elapsed = end - start
print(1 if elapsed < 12.0 else 0, f"{elapsed:.3f}")
PY
)"
IFS=' ' read -r elapsed_ok elapsed_seconds <<<"${elapsed_data}" || elapsed_ok=0

if [ "${elapsed_ok}" != "1" ]; then
  elapsed_seconds="${elapsed_seconds:-unknown}"
  printf 'D-Bus fallback took too long (elapsed=%ss)\n' "${elapsed_seconds}" >&2
  exit 1
fi

if ! grep -q 'fallback=dbus_unavailable' <<<"${command_output}"; then
  printf '%s\n' "${command_output}" >&2
  echo "expected dbus fallback log missing" >&2
  exit 1
fi

if ! grep -q 'dbus=unavailable' <<<"${command_output}"; then
  printf '%s\n' "${command_output}" >&2
  echo "expected dbus note missing" >&2
  exit 1
fi

service_file="${TMP_DIR}/avahi/k3s-sugar-dev.service"
if [ ! -f "${service_file}" ]; then
  printf '%s\n' "${command_output}" >&2
  echo "service file not written" >&2
  exit 1
fi

if [ ! -s "${API_READY_LOG}" ]; then
  echo "API readiness helper was not invoked" >&2
  exit 1
fi

if [ ! -s "${BUSCTL_LOG}" ]; then
  printf '%s\n' "${command_output}" >&2
  echo "busctl stub was not called" >&2
  exit 1
fi

echo "${command_output}" | grep -q 'outcome=ok role=server' || {
  printf '%s\n' "${command_output}" >&2
  echo "publish outcome log missing" >&2
  exit 1
}

: >"${API_READY_LOG}"
: >"${INSTALL_LOG}"
: >"${RESOLVE_LOG}"
: >"${GETENT_LOG}"

export SUGARKUBE_SERVERS=2
export SUGARKUBE_TOKEN="$(printf "dummy")"
export DISCOVERY_ATTEMPTS=1
export DISCOVERY_WAIT_SECS=0

set +e
follower_log="${TMP_DIR}/discover-follower.log"
COMMAND_TIMEOUT=20 DISCOVER_LOG="${follower_log}" python3 - "${DISCOVER_SCRIPT}" <<'PY'
import os
import subprocess
import sys

script = sys.argv[1]
log_path = os.environ.get("DISCOVER_LOG", "")
timeout = float(os.environ.get("COMMAND_TIMEOUT", "20"))

if not log_path:
    raise SystemExit(2)

with open(log_path, "w", encoding="utf-8") as handle:
    proc = subprocess.Popen(
        [script],
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        return_code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        return_code = 124
    sys.exit(return_code)
PY
follower_status=$?
follower_output="$(cat "${follower_log}" 2>/dev/null)"
set -e

if [ "${follower_status}" -ne 0 ]; then
  printf '%s\n' "${follower_output}" >&2
  echo "follower discover run exited with ${follower_status}" >&2
  exit 1
fi

if ! grep -q 'fallback=dbus_unavailable' <<<"${follower_output}"; then
  printf '%s\n' "${follower_output}" >&2
  echo "expected dbus fallback log missing in follower run" >&2
  exit 1
fi

if ! grep -q 'accept_path=nss' <<<"${follower_output}"; then
  printf '%s\n' "${follower_output}" >&2
  echo "expected accept_path=nss log missing" >&2
  exit 1
fi

if ! grep -q 'nss_ok=1' <<<"${follower_output}"; then
  printf '%s\n' "${follower_output}" >&2
  echo "expected nss_ok log missing" >&2
  exit 1
fi

if ! grep -q 'browse_ok=1' <<<"${follower_output}"; then
  printf '%s\n' "${follower_output}" >&2
  echo "expected browse_ok log missing" >&2
  exit 1
fi

if ! grep -q 'mode=alive' <<<"${follower_output}"; then
  printf '%s\n' "${follower_output}" >&2
  echo "expected mode field missing" >&2
  exit 1
fi

if [ ! -s "${API_READY_LOG}" ]; then
  printf '%s\n' "${follower_output}" >&2
  echo "API readiness helper was not invoked for follower run" >&2
  exit 1
fi

if ! grep -q 'SERVER_HOST=sugarkube0.local' "${API_READY_LOG}"; then
  cat "${API_READY_LOG}" >&2
  echo "SERVER_HOST not recorded for follower run" >&2
  exit 1
fi

if ! grep -q 'SERVER_IP=198.51.100.25' "${API_READY_LOG}"; then
  cat "${API_READY_LOG}" >&2
  echo "SERVER_IP not recorded for follower run" >&2
  exit 1
fi

if [ ! -s "${INSTALL_LOG}" ]; then
  printf '%s\n' "${follower_output}" >&2
  echo "k3s install stub was not invoked for follower run" >&2
  exit 1
fi

if ! grep -q 'https://sugarkube0.local:6443' "${INSTALL_LOG}"; then
  cat "${INSTALL_LOG}" >&2
  echo "expected K3S_URL not recorded for follower run" >&2
  exit 1
fi

if [ ! -s "${RESOLVE_LOG}" ]; then
  printf '%s\n' "${follower_output}" >&2
  echo "avahi-resolve stub was not called in follower run" >&2
  exit 1
fi
