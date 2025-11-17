#!/bin/bash
set -euo pipefail
# Sanitized mDNS / k3s debug script for sugarkube nodes.
# Produces output that is safe to commit to the repo by:
# - Redacting IP and MAC addresses
# - Filtering avahi-browse output to an allowlist of hostnames + k3s service
# - Summarizing tcpdump / ping / curl results instead of printing raw packets

###############################################################################
# Config: allowed hostnames in logs
###############################################################################

# Default allowlist for sugarkube project. Override at runtime with:
#   MDNS_ALLOWED_HOSTS="sugarkube0 sugarkube1 sugarkube2" ./debug-mdns.sh
# or before running `just up dev`:
#   export MDNS_ALLOWED_HOSTS="sugarkube0 sugarkube1 sugarkube2"
ALLOWED_HOSTS_DEFAULT=("sugarkube0" "sugarkube1" "sugarkube2")

if [[ -n "${MDNS_ALLOWED_HOSTS:-}" ]]; then
  # Split MDNS_ALLOWED_HOSTS on whitespace into an array
  read -r -a ALLOWED_HOSTS <<< "${MDNS_ALLOWED_HOSTS}"
else
  ALLOWED_HOSTS=("${ALLOWED_HOSTS_DEFAULT[@]}")
fi

PRIMARY_HOST="${ALLOWED_HOSTS[0]:-sugarkube0}"

###############################################################################
# Helper functions
###############################################################################

sanitize_ip_mac() {
  # Redact IPv4, IPv6, and MAC addresses from stdin
  sed -E \
    -e 's/(^|[^0-9])([0-9]{1,3}(\.[0-9]{1,3}){3})([^0-9]|$)/\1<REDACTED_IPV4>\4/g' \
    -e 's/([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}/<REDACTED_MAC>/g' \
    -e 's/\b([0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}\b/<REDACTED_IPV6>/g' \
    -e 's/\b([0-9A-Fa-f]{1,4}:){1,7}:\b/<REDACTED_IPV6>/g' \
    -e 's/\b:((:[0-9A-Fa-f]{1,4}){1,7})\b/<REDACTED_IPV6>/g' \
    -e 's/\b([0-9A-Fa-f]{1,4}:){1,6}:[0-9A-Fa-f]{1,4}\b/<REDACTED_IPV6>/g' \
    -e 's/::1/<REDACTED_IPV6>/g'
}

filter_avahi_output() {
  # Filter avahi-browse output:
  # - Always keep lines mentioning _k3s-sugar-dev._tcp
  # - Keep any line that contains an allowed hostname
  local line
  while IFS= read -r line; do
    if [[ "$line" == *"_k3s-sugar-dev._tcp"* ]]; then
      echo "$line"
      continue
    fi

    for ah in "${ALLOWED_HOSTS[@]}"; do
      if [[ "$line" == *"$ah"* ]]; then
        echo "$line"
        break
      fi
    done
  done
}

browse_and_filter() {
  local failure_message="$1"
  shift

  if command -v avahi-browse >/dev/null 2>&1; then
    timeout 5 avahi-browse "$@" 2>/dev/null | filter_avahi_output | sanitize_ip_mac || \
      echo "$failure_message"
  else
    echo "avahi-browse not installed"
  fi
}

resolve_and_redact() {
  # Resolve a hostname via avahi and print a redacted result
  local host="$1"
  local resolved
  if resolved="$(avahi-resolve -n "$host" 2>/dev/null)"; then
    # Resolved, but redact address
    echo "${host}    <REDACTED_IP>"
  else
    echo "${host}    <RESOLUTION_FAILED>"
  fi
}

print_section() {
  echo
  echo "=== $1 ==="
}

###############################################################################
# Script body
###############################################################################

print_section "System Info"
hostname
date -u
ip addr show eth0 | sanitize_ip_mac

print_section "Avahi Daemon Status"
sudo systemctl status avahi-daemon --no-pager 2>&1 || \
  echo "avahi-daemon status unavailable"

print_section "Check if mDNS port is listening"
# This only shows 0.0.0.0:5353, which is not sensitive
if command -v netstat >/dev/null 2>&1; then
  sudo netstat -ulnp 2>/dev/null | grep 5353 || \
    echo "No process listening on UDP 5353 via netstat"
elif command -v ss >/dev/null 2>&1; then
  sudo ss -ulnp 2>/dev/null | grep 5353 || echo "No process listening on UDP 5353 via ss"
else
  echo "Neither netstat nor ss available"
fi

print_section "Test local mDNS resolution (redacted)"
for h in "${ALLOWED_HOSTS[@]}"; do
  resolve_and_redact "$h"
done

print_section "Browse all mDNS services (5 second timeout, filtered)"
browse_and_filter "Browse timed out or no *allowed* services found" -a -t -r

print_section "Browse specific k3s service (5 second timeout, filtered)"
browse_and_filter "Browse timed out or no k3s service found" -t -r _k3s-sugar-dev._tcp

print_section "Check for multicast route"
ip route show 2>/dev/null | grep 224.0.0.0 | sanitize_ip_mac || \
  echo "No explicit multicast route line for 224.0.0.0 found"

print_section "Check firewall rules"
if command -v iptables >/dev/null 2>&1; then
  sudo iptables -L -n -v 2>/dev/null | grep -E "5353|mdns|multicast" || \
    echo "No explicit firewall rules for mDNS"
else
  echo "iptables not installed"
fi
sudo ufw status 2>/dev/null || echo "UFW not installed/active"

print_section "Check if we can ping ${PRIMARY_HOST} (summary only)"
if ping -c 3 -W 1 "${PRIMARY_HOST}" >/dev/null 2>&1; then
  echo "Ping to ${PRIMARY_HOST}: SUCCESS (3/3 replies)"
else
  echo "Ping to ${PRIMARY_HOST}: FAILED"
fi

print_section "Check nsswitch.conf for mDNS"
grep -E 'mdns' /etc/nsswitch.conf || echo "No mdns entry in /etc/nsswitch.conf"

print_section "Test if we can reach ${PRIMARY_HOST}'s k3s API (summary only)"
if curl -k --connect-timeout 5 -sS "https://${PRIMARY_HOST}:6443/ping" >/dev/null 2>&1; then
  echo "k3s API via mDNS hostname: OK"
else
  echo "k3s API via mDNS hostname: FAILED"
fi

# If an IPv4 for the primary host is configured in /etc/hosts or resolvable, we
# can also test via its IPv4, but we never print the IP itself.
if avahi-resolve -n "${PRIMARY_HOST}" >/dev/null 2>/dev/null; then
  if curl -k --connect-timeout 5 -sS "https://${PRIMARY_HOST}:6443/ping" >/dev/null 2>&1; then
    echo "k3s API via ${PRIMARY_HOST} (as IP): OK"
  else
    echo "k3s API via ${PRIMARY_HOST} (as IP): FAILED"
  fi
fi

print_section "Check for multicast group membership (safe addresses only)"
ip maddress show eth0 2>/dev/null || echo "No multicast membership information for eth0"

print_section "Capture mDNS traffic (5 second sample, summarized)"
if command -v tcpdump >/dev/null 2>&1; then
  # Capture up to 5 packets but discard payload; only report if any were seen
  if sudo timeout 5 tcpdump -i eth0 -n udp port 5353 -c 5 >/dev/null 2>&1; then
    echo "Observed at least one mDNS packet on udp/5353 during 5s window"
  else
    echo "No mDNS packets observed on udp/5353 during 5s window (or tcpdump error)"
  fi
else
  echo "tcpdump not installed"
fi

print_section "Check Avahi daemon logs (last 50 lines)"
sudo journalctl -u avahi-daemon -n 50 --no-pager 2>&1 | sanitize_ip_mac

print_section "Allowed hostnames in this sanitized log"
for h in "${ALLOWED_HOSTS[@]}"; do
  echo " - $h"
done

print_section "DONE"
