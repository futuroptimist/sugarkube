#!/usr/bin/env bash
set -euo pipefail

# mdns_diag.sh - One-shot mDNS diagnostic for troubleshooting discovery failures
# This script checks systemctl services, avahi-browse, and avahi-resolve,
# then prints suggested remediation based on exit codes.

# Default hostname to check
HOSTNAME_TO_CHECK="${MDNS_DIAG_HOSTNAME:-sugarkube0.local}"

# Default service type to browse
SERVICE_CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
SERVICE_ENV="${SUGARKUBE_ENV:-dev}"
SERVICE_TYPE="_k3s-${SERVICE_CLUSTER}-${SERVICE_ENV}._tcp"
STUB_MODE="${MDNS_DIAG_STUB_MODE:-0}"

# Track failures
declare -a FAILURES=()
declare -a WARNINGS=()

# Parse command-line arguments
while [ "$#" -gt 0 ]; do
  case "$1" in
    --hostname)
      if [ "$#" -lt 2 ]; then
        echo "ERROR: --hostname requires a value" >&2
        exit 2
      fi
      HOSTNAME_TO_CHECK="$2"
      shift 2
      ;;
    --service-type)
      if [ "$#" -lt 2 ]; then
        echo "ERROR: --service-type requires a value" >&2
        exit 2
      fi
      SERVICE_TYPE="$2"
      shift 2
      ;;
    --help)
      cat <<'EOF'
Usage: mdns_diag.sh [--hostname NAME] [--service-type TYPE]

One-shot mDNS diagnostic for troubleshooting discovery failures.

Options:
  --hostname NAME       Hostname to resolve (default: sugarkube0.local)
  --service-type TYPE   mDNS service type to browse (default: _k3s-sugar-dev._tcp)
  --help                Show this help message

Environment variables:
  MDNS_DIAG_HOSTNAME    Default hostname to check (overridden by --hostname)
  SUGARKUBE_CLUSTER     Cluster name for service type (default: sugar)
  SUGARKUBE_ENV         Environment name for service type (default: dev)
  MDNS_DIAG_STUB_MODE   When set to a non-zero value, skip Avahi/NSS checks and
                        emit a quick, local-only diagnostic

Exit codes:
  0   All checks passed
  1   One or more checks failed
  2   Invalid arguments
EOF
      exit 0
      ;;
    *)
      echo "ERROR: Unknown option: $1" >&2
      echo "Run with --help for usage information" >&2
      exit 2
      ;;
  esac
done

# Ensure hostname has .local suffix
case "${HOSTNAME_TO_CHECK}" in
  *.local) ;;
  *) HOSTNAME_TO_CHECK="${HOSTNAME_TO_CHECK}.local" ;;
esac

echo "=== mDNS Diagnostic ==="
echo "Hostname: ${HOSTNAME_TO_CHECK}"
echo "Service:  ${SERVICE_TYPE}"
echo ""

if [ "${STUB_MODE}" != "0" ]; then
  echo "Stub mode enabled; skipping Avahi and NSS checks."
  echo "Unset MDNS_DIAG_STUB_MODE to run full diagnostics."
  exit 0
fi

# Check 1: systemctl is-active dbus
echo "▶ Checking D-Bus service..."
if command -v systemctl >/dev/null 2>&1; then
  if systemctl is-active --quiet dbus 2>/dev/null; then
    echo "  ✓ dbus is active"
  else
    echo "  ✗ dbus is not active"
    FAILURES+=("dbus service is not running")
  fi
else
  echo "  ⚠ systemctl not available, skipping dbus check"
  WARNINGS+=("systemctl not available to check dbus")
fi

# Check 2: systemctl is-active avahi-daemon
echo "▶ Checking Avahi daemon..."
if command -v systemctl >/dev/null 2>&1; then
  if systemctl is-active --quiet avahi-daemon 2>/dev/null; then
    echo "  ✓ avahi-daemon is active"
  else
    echo "  ✗ avahi-daemon is not active"
    FAILURES+=("avahi-daemon service is not running")
  fi
else
  echo "  ⚠ systemctl not available, checking for avahi-daemon process"
  if command -v pgrep >/dev/null 2>&1 && pgrep -x avahi-daemon >/dev/null 2>&1; then
    echo "  ✓ avahi-daemon process found"
  else
    echo "  ✗ avahi-daemon process not found"
    FAILURES+=("avahi-daemon is not running")
  fi
fi

# Check 3: avahi-browse for k3s services
echo "▶ Browsing for ${SERVICE_TYPE} services..."
if command -v avahi-browse >/dev/null 2>&1; then
  browse_output=""
  browse_status=0
  browse_retries="${MDNS_DIAG_BROWSE_RETRIES:-2}"
  case "${browse_retries}" in
    ''|*[!0-9]*) browse_retries=2 ;;
  esac
  if [ "${browse_retries}" -lt 1 ]; then
    browse_retries=1
  fi

  # Retry avahi-browse in case daemon is still initializing
  for attempt in $(seq 1 "${browse_retries}"); do
    browse_output=""
    browse_status=0
    # Use timeout command to prevent hanging, fallback to script's --timeout if timeout unavailable
    if command -v timeout >/dev/null 2>&1; then
      browse_output="$(timeout 5 avahi-browse -rt "${SERVICE_TYPE}" --timeout=3 2>&1)" || browse_status=$?
    else
      browse_output="$(avahi-browse -rt "${SERVICE_TYPE}" --timeout=3 2>&1)" || browse_status=$?
    fi

    if [ "${browse_status}" -eq 0 ]; then
      break
    fi

    # If not the last attempt, wait before retrying
    if [ "${attempt}" -lt "${browse_retries}" ]; then
      sleep 1
    fi
  done

  if [ "${browse_status}" -eq 0 ]; then
    service_count="$(printf '%s\n' "${browse_output}" | grep -c '^=' || true)"
    if [ "${service_count}" -gt 0 ]; then
      echo "  ✓ Found ${service_count} service(s)"
      # Show first few services
      printf '%s\n' "${browse_output}" | grep '^=' | head -n 3 | sed 's/^/    /'
    else
      echo "  ⚠ No services found"
      WARNINGS+=("No ${SERVICE_TYPE} services discovered on the network")
    fi
  else
    if [ "${browse_retries}" -gt 1 ]; then
      echo "  ✗ avahi-browse failed (exit code: ${browse_status}) after ${browse_retries} attempts"
      FAILURES+=("avahi-browse command failed after ${browse_retries} retries (daemon may be restarting)")
    else
      echo "  ✗ avahi-browse failed (exit code: ${browse_status})"
      FAILURES+=("avahi-browse command failed")
    fi
  fi
else
  echo "  ✗ avahi-browse command not found"
  FAILURES+=("avahi-browse is not installed")
fi

# Check 4: avahi-resolve for specific hostname
echo "▶ Resolving ${HOSTNAME_TO_CHECK}..."
if command -v avahi-resolve >/dev/null 2>&1; then
  resolve_output=""
  resolve_status=0
  # Use timeout to prevent hanging
  if command -v timeout >/dev/null 2>&1; then
    resolve_output="$(timeout 5 avahi-resolve -n "${HOSTNAME_TO_CHECK}" -4 2>&1)" || resolve_status=$?
  else
    resolve_output="$(avahi-resolve -n "${HOSTNAME_TO_CHECK}" -4 2>&1)" || resolve_status=$?
  fi

  if [ "${resolve_status}" -eq 0 ] && [ -n "${resolve_output}" ]; then
    resolved_ip="$(printf '%s\n' "${resolve_output}" | awk '{print $2}' | head -n1)"
    if [ -n "${resolved_ip}" ]; then
      echo "  ✓ Resolved to ${resolved_ip}"
    else
      echo "  ⚠ Resolution succeeded but no IP found"
      WARNINGS+=("${HOSTNAME_TO_CHECK} resolved but no IP address returned")
    fi
  else
    echo "  ✗ Failed to resolve ${HOSTNAME_TO_CHECK}"
    FAILURES+=("Cannot resolve ${HOSTNAME_TO_CHECK}")
  fi
else
  echo "  ✗ avahi-resolve command not found"
  FAILURES+=("avahi-resolve is not installed")
fi

# Check 5: NSS resolution via getent
echo "▶ Checking NSS mDNS resolution..."
if command -v getent >/dev/null 2>&1; then
  getent_output=""
  getent_status=0
  # Use timeout to prevent hanging on mDNS lookups
  if command -v timeout >/dev/null 2>&1; then
    getent_output="$(timeout 5 getent hosts "${HOSTNAME_TO_CHECK}" 2>&1)" || getent_status=$?
  else
    getent_output="$(getent hosts "${HOSTNAME_TO_CHECK}" 2>&1)" || getent_status=$?
  fi

  if [ "${getent_status}" -eq 0 ] && [ -n "${getent_output}" ]; then
    resolved_ip="$(printf '%s\n' "${getent_output}" | awk '{print $1}' | head -n1)"
    if [ -n "${resolved_ip}" ]; then
      echo "  ✓ NSS resolved to ${resolved_ip}"
    else
      echo "  ⚠ NSS resolution succeeded but no IP found"
    fi
  else
    echo "  ⚠ NSS failed to resolve ${HOSTNAME_TO_CHECK}"
    WARNINGS+=("NSS cannot resolve .local addresses (check /etc/nsswitch.conf)")
  fi
else
  echo "  ⚠ getent command not found"
fi

# Check 6: Avahi configuration
echo "▶ Checking Avahi configuration..."
avahi_conf="/etc/avahi/avahi-daemon.conf"
if [ -r "${avahi_conf}" ]; then
  # Check if D-Bus is disabled
  if grep -q '^[[:space:]]*enable-dbus[[:space:]]*=[[:space:]]*no' "${avahi_conf}" 2>/dev/null; then
    echo "  ⚠ D-Bus is disabled in Avahi configuration"
    WARNINGS+=("D-Bus is disabled in ${avahi_conf} (may limit functionality)")
  else
    echo "  ✓ Avahi configuration looks OK"
  fi
else
  echo "  ⚠ Cannot read ${avahi_conf}"
fi

# Print summary and remediation
echo ""
echo "=== Summary ==="

if [ "${#FAILURES[@]}" -eq 0 ] && [ "${#WARNINGS[@]}" -eq 0 ]; then
  echo "✓ All checks passed"
  exit 0
fi

if [ "${#WARNINGS[@]}" -gt 0 ]; then
  echo ""
  echo "Warnings (${#WARNINGS[@]}):"
  for warning in "${WARNINGS[@]}"; do
    echo "  ⚠ ${warning}"
  done
fi

if [ "${#FAILURES[@]}" -gt 0 ]; then
  echo ""
  echo "Failures (${#FAILURES[@]}):"
  for failure in "${FAILURES[@]}"; do
    echo "  ✗ ${failure}"
  done

  echo ""
  echo "=== Suggested Remediation ==="

  # Provide specific remediation based on failures
  for failure in "${FAILURES[@]}"; do
    case "${failure}" in
      *"dbus service is not running"*)
        echo "• Start D-Bus service:"
        echo "    sudo systemctl start dbus"
        echo "    sudo systemctl enable dbus"
        ;;
      *"avahi-daemon"*"not running"*)
        echo "• Start Avahi daemon:"
        echo "    sudo systemctl start avahi-daemon"
        echo "    sudo systemctl enable avahi-daemon"
        ;;
      *"avahi-browse"*"not installed"*)
        echo "• Install Avahi tools:"
        echo "    sudo apt install avahi-utils  # Debian/Ubuntu"
        echo "    sudo dnf install avahi-tools  # Fedora/RHEL"
        ;;
      *"avahi-resolve"*"not installed"*)
        echo "• Install Avahi tools:"
        echo "    sudo apt install avahi-utils  # Debian/Ubuntu"
        echo "    sudo dnf install avahi-tools  # Fedora/RHEL"
        ;;
      *"Cannot resolve"*)
        echo "• Verify the hostname ${HOSTNAME_TO_CHECK} is advertising on the network"
        echo "• Check firewall rules allow mDNS (UDP port 5353)"
        echo "• Verify all nodes are on the same network segment"
        ;;
      *"avahi-browse command failed"*)
        echo "• Check Avahi daemon logs:"
        echo "    journalctl -u avahi-daemon -n 50"
        echo "• Restart Avahi daemon:"
        echo "    sudo systemctl restart avahi-daemon"
        ;;
    esac
  done

  # Additional general remediation
  if printf '%s\n' "${FAILURES[@]}" | grep -q "NSS"; then
    echo "• Configure NSS for mDNS resolution:"
    echo "    Edit /etc/nsswitch.conf and ensure 'hosts' line includes 'mdns4_minimal [NOTFOUND=return]' before 'dns'"
    echo "    Example: hosts: files mdns4_minimal [NOTFOUND=return] dns"
  fi

  echo ""
  echo "For more information, see:"
  echo "  • Avahi documentation: https://avahi.org/"
  echo "  • Sugarkube docs: docs/pi-cluster-bootstrap.md"

  exit 1
fi

exit 0
