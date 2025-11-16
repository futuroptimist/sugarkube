#!/bin/bash
# Sanitized mDNS / k3s debug script for sugarkube nodes.
# Produces output that is safe to commit to the repo by:
# - Redacting IP and MAC addresses
# - Filtering avahi-browse output to an allowlist of hostnames + k3s service
# - Summarizing tcpdump / ping / curl results instead of printing raw packets

###############################################################################
# Config: allowed hostnames in logs
###############################################################################

# Default allowlist for sugarkube project. Override at runtime with:
#   MDNS_ALLOWED_HOSTS="sugarkube0.local sugarkube1.local other.local" ./debug-mdns.sh
ALLOWED_HOSTS_DEFAULT=("sugarkube0.local" "sugarkube1.local" "sugarkube2.local")

if [[ -n "${MDNS_ALLOWED_HOSTS:-}" ]]; then
  # Split MDNS_ALLOWED_HOSTS on whitespace into an array
  read -r -a ALLOWED_HOSTS <<< "${MDNS_ALLOWED_HOSTS}"
else
  ALLOWED_HOSTS=("${ALLOWED_HOSTS_DEFAULT[@]}")
fi

###############################################################################
# Helper functions
###############################################################################

sanitize_ip_mac() {
  # Redact IPv4, IPv6, and MAC addresses from stdin
  sed -E \
    -e 's/([0-9]{1,3}\.){3}[0-9]{1,3}/<REDACTED_IPV4>/g' \
    -e 's/([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}/<REDACTED_MAC>/g' \
    -e 's/[0-9A-Fa-f]{0,4}(:[0-9A-Fa-f]{0,4}){2,7}/<REDACTED_IPV6>/g'
}

is_allowed_host() {
  local host="$1"
  for ah in "${ALLOWED_HOSTS[@]}"; do
    if [[ "$host" == "$ah" ]]; then
      return 0
    fi
  done
  return 1
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
sudo systemctl status avahi-daemon --no-pager 2>&1

print_section "Check if mDNS port is listening"
# This only shows 0.0.0.0:5353, which is not sensitive
if command -v netstat >/dev/null 2>&1; then
  sudo netstat -ulnp 2>/dev/null | grep 5353 || echo "No process listening on UDP 5353 via netstat"
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
if command -v avahi-browse >/dev/null 2>&1; then
  timeout 5 avahi-browse -a -t -r 2>/dev/null | filter_avahi_output | sanitize_ip_mac || \
    echo "Browse timed out or no *allowed* services found"
else
  echo "avahi-browse not installed"
fi

print_section "Browse specific k3s service (5 second timeout, filtered)"
if command -v avahi-browse >/dev/null 2>&1; then
  timeout 5 avahi-browse -t -r _k3s-sugar-dev._tcp 2>/dev/null | filter_avahi_output | \
    sanitize_ip_mac || echo "Browse timed out or no k3s service found"
else
  echo "avahi-browse not installed"
fi

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

print_section "Check if we can ping sugarkube0.local (summary only)"
if ping -c 3 -W 1 sugarkube0.local >/dev/null 2>&1; then
  echo "Ping to sugarkube0.local: SUCCESS (3/3 replies)"
else
  echo "Ping to sugarkube0.local: FAILED"
fi

print_section "Try to discover k3s service on sugarkube0 specifically (filtered)"
if command -v avahi-browse >/dev/null 2>&1; then
  timeout 5 avahi-browse -t -r _k3s-sugar-dev._tcp 2>/dev/null | filter_avahi_output | \
    sanitize_ip_mac || echo "No k3s-sugar-dev service for sugarkube0 found"
else
  echo "avahi-browse not installed"
fi

print_section "Check nsswitch.conf for mDNS"
grep -E 'mdns' /etc/nsswitch.conf || echo "No mdns entry in /etc/nsswitch.conf"

print_section "Test if we can reach sugarkube0's k3s API (summary only)"
if curl -k --connect-timeout 5 -sS https://sugarkube0.local:6443/ping >/dev/null 2>&1; then
  echo "k3s API via mDNS hostname: OK"
else
  echo "k3s API via mDNS hostname: FAILED"
fi

# If an IPv4 for sugarkube0.local is configured in /etc/hosts or resolvable, we
# can also test via its IPv4, but we never print the IP itself.
if avahi-resolve -n sugarkube0.local >/dev/null 2>&1; then
  if curl -k --connect-timeout 5 -sS https://sugarkube0.local:6443/ping >/dev/null 2>&1; then
    echo "k3s API via sugarkube0.local (as IP): OK"
  else
    echo "k3s API via sugarkube0.local (as IP): FAILED"
  fi
fi

print_section "Check for multicast group membership (safe addresses only)"
ip maddress show eth0 2>/dev/null | sanitize_ip_mac || \
  echo "No multicast membership information for eth0"

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
sudo journalctl -u avahi-daemon -n 50 --no-pager 2>&1

print_section "Allowed hostnames in this sanitized log"
for h in "${ALLOWED_HOSTS[@]}"; do
  echo " - $h"
done

print_section "DONE"
