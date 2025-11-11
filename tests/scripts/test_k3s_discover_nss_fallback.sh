#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DISCOVER_SCRIPT="${REPO_ROOT}/scripts/k3s-discover.sh"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

BIN_DIR="${TMP_DIR}/bin"
mkdir -p "${BIN_DIR}" "${TMP_DIR}/avahi"

DISCOVER_LOG="${TMP_DIR}/discover.log"
API_READY_LOG="${TMP_DIR}/api-ready.log"
INSTALL_LOG="${TMP_DIR}/install.log"
export API_READY_LOG

real_ip_bin="$(command -v ip || true)"

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

cat >"${BIN_DIR}/sleep" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${BIN_DIR}/sleep"

cat >"${BIN_DIR}/ip" <<SH
#!/usr/bin/env bash
set -euo pipefail
if [ "\$#" -ge 4 ] && [ "\$1" = "-4" ] && [ "\$2" = "-o" ] && [ "\$3" = "addr" ] && [ "\$4" = "show" ]; then
  echo "2: eth0    inet 192.0.2.99/24 brd 192.0.2.255 scope global eth0"
  exit 0
fi
if [ -n "${real_ip_bin}" ]; then
  exec "${real_ip_bin}" "\$@"
fi
echo "unsupported ip args: \$*" >&2
exit 1
SH
chmod +x "${BIN_DIR}/ip"

cat >"${BIN_DIR}/iptables" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${BIN_DIR}/iptables"

cat >"${BIN_DIR}/ip6tables" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${BIN_DIR}/ip6tables"

cat >"${BIN_DIR}/apt-get" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${BIN_DIR}/apt-get"

cat >"${BIN_DIR}/avahi-browse" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cat <<'OUT'
=;eth0;IPv4;k3s API sugar/dev [server] on sugarkube0;_k3s-sugar-dev._tcp;local;sugarkube0.local;;6443;txt=role=server,mode=ready
OUT
exit 0
SH
chmod +x "${BIN_DIR}/avahi-browse"

cat >"${BIN_DIR}/avahi-resolve" <<'SH'
#!/usr/bin/env bash
exit 1
SH
chmod +x "${BIN_DIR}/avahi-resolve"

cat >"${BIN_DIR}/avahi-publish-service" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
while read -r -t 0.1 _; do
  :
done
sleep 0.1
exit 0
SH
chmod +x "${BIN_DIR}/avahi-publish-service"

cat >"${BIN_DIR}/avahi-publish" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
while read -r -t 0.1 _; do
  :
done
sleep 0.1
exit 0
SH
chmod +x "${BIN_DIR}/avahi-publish"

cat >"${BIN_DIR}/getent" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  ahostsv4)
    echo "192.0.2.10 STREAM sugarkube0.local"
    exit 0
    ;;
  ahostsv6)
    exit 2
    ;;
  hosts)
    echo "192.0.2.10 sugarkube0.local"
    exit 0
    ;;
  *)
    exit 2
    ;;
esac
SH
chmod +x "${BIN_DIR}/getent"

cat >"${BIN_DIR}/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cat <<'SCRIPT'
#!/usr/bin/env sh
exit 0
SCRIPT
SH
chmod +x "${BIN_DIR}/curl"

cat >"${BIN_DIR}/sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [ -n "${SH_LOG_PATH:-}" ]; then
  printf 'env:K3S_URL=%s\n' "${K3S_URL:-}" >> "${SH_LOG_PATH}"
  printf 'args:%s\n' "$*" >> "${SH_LOG_PATH}"
fi
cat >/dev/null
exit 0
SH
chmod +x "${BIN_DIR}/sh"

cat >"${BIN_DIR}/l4_probe.sh" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${BIN_DIR}/l4_probe.sh"

cat >"${BIN_DIR}/configure_avahi.sh" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${BIN_DIR}/configure_avahi.sh"

cat >"${BIN_DIR}/check_apiready.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'ts=%s event=apiready outcome=ok host=%s port=%s mode=ready\n' \
  "$(date -Is 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S')" \
  "${SERVER_HOST:-}" \
  "${SERVER_PORT:-}" >> "${API_READY_LOG}"
exit 0
SH
chmod +x "${BIN_DIR}/check_apiready.sh"

cat >"${BIN_DIR}/mdns-selfcheck.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'ts=%s event=mdns_selfcheck outcome=skip role=%s phase=%s\n' \
  "$(date -Is 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S')" \
  "${ROLE:-server}" \
  "${PHASE:-server}" >/dev/null
exit 0
SH
chmod +x "${BIN_DIR}/mdns-selfcheck.sh"

export PATH="${BIN_DIR}:${PATH}"
export SH_LOG_PATH="${INSTALL_LOG}"
export ALLOW_NON_ROOT=1
export SUGARKUBE_SKIP_SYSTEMCTL=1
export SUGARKUBE_SKIP_MDNS_SELF_CHECK=1
export SUGARKUBE_CLUSTER="sugar"
export SUGARKUBE_ENV="dev"
export SUGARKUBE_MDNS_HOST="cube.local"
export SUGARKUBE_AVAHI_SERVICE_DIR="${TMP_DIR}/avahi"
export SUGARKUBE_API_READY_CHECK_BIN="${BIN_DIR}/check_apiready.sh"
export SUGARKUBE_MDNS_SELF_CHECK_BIN="${BIN_DIR}/mdns-selfcheck.sh"
export SUGARKUBE_MDNS_BOOT_RETRIES=1
export SUGARKUBE_MDNS_BOOT_DELAY=0
export SUGARKUBE_MDNS_SERVER_RETRIES=1
export SUGARKUBE_MDNS_SERVER_DELAY=0
export SUGARKUBE_TEST_SKIP_PUBLISH_SLEEP=1
export SUGARKUBE_MDNS_ABSENCE_GATE=0
export HOSTNAME="cube.local"
export SUGARKUBE_TOKEN="testtoken"
export SUGARKUBE_SKIP_AVAHI_LIVENESS=1

set +e
COMMAND_TIMEOUT=12 DISCOVER_LOG="${DISCOVER_LOG}" python3 - "${DISCOVER_SCRIPT}" <<'PY'
import os
import subprocess
import sys

script = sys.argv[1]
log_path = os.environ.get("DISCOVER_LOG", "")
timeout = float(os.environ.get("COMMAND_TIMEOUT", "12"))

with open(log_path, "w", encoding="utf-8") as handle:
    proc = subprocess.Popen(
        [script],
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        rc = 124
    sys.exit(rc)
PY
status=$?
set -e

command_output="$(cat "${DISCOVER_LOG}" 2>/dev/null)"

if [ "${status}" -ne 0 ]; then
  printf '%s\n' "${command_output}" >&2
  echo "k3s-discover.sh exited with ${status}" >&2
  exit 1
fi

if ! grep -q 'accept_path=nss' <<<"${command_output}"; then
  printf '%s\n' "${command_output}" >&2
  echo "expected NSS fallback acceptance log missing" >&2
  exit 1
fi

if ! grep -q 'resolve_ok=0' <<<"${command_output}"; then
  printf '%s\n' "${command_output}" >&2
  echo "resolve_ok should be 0 when avahi address missing" >&2
  exit 1
fi

if ! grep -q 'nss_ok=1' <<<"${command_output}"; then
  printf '%s\n' "${command_output}" >&2
  echo "expected nss_ok=1 in logs" >&2
  exit 1
fi

if ! grep -q 'env:K3S_URL=https://sugarkube0.local:6443' "${INSTALL_LOG}"; then
  printf '%s\n' "${command_output}" >&2
  echo "installer did not use hostname-based K3S_URL" >&2
  exit 1
fi

if [ ! -s "${API_READY_LOG}" ]; then
  printf '%s\n' "${command_output}" >&2
  echo "API readiness helper was not invoked" >&2
  exit 1
fi

printf '%s\n' "${command_output}"
