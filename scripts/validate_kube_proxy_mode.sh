#!/usr/bin/env bash
# Purpose: Validate kube-proxy dataplane mode configuration and print diagnostic info
# Usage: ./scripts/validate_kube_proxy_mode.sh [--config-dir PATH]
set -euo pipefail

CONFIG_DIR="/etc/rancher/k3s/config.yaml.d"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config-dir)
      if [[ $# -lt 2 ]]; then
        echo "--config-dir requires a path argument" >&2
        exit 1
      fi
      CONFIG_DIR="$2"
      shift 2
      ;;
    --help)
      cat <<'EOF'
Usage: validate_kube_proxy_mode.sh [--config-dir PATH]

Validates the kube-proxy dataplane mode configuration and reports:
  - Configured proxy mode from k3s config files
  - Availability of required binaries (nft for nftables, iptables for legacy)
  - Whether configuration matches available tools

Options:
  --config-dir PATH  Path to k3s config directory (default: /etc/rancher/k3s/config.yaml.d)
  --help             Show this message
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

# Determine configured proxy mode
CONFIGURED_MODE="unknown"
if [[ -d "$CONFIG_DIR" ]]; then
  for config_file in "$CONFIG_DIR"/*.yaml; do
    if [[ -f "$config_file" ]]; then
      if grep -q "proxy-mode=nftables\|proxy-mode=nft" "$config_file" 2>/dev/null; then
        CONFIGURED_MODE="nftables"
        break
      elif grep -q "proxy-mode=iptables" "$config_file" 2>/dev/null; then
        CONFIGURED_MODE="iptables"
        break
      fi
    fi
  done
fi

# Check for nft binary
NFT_AVAILABLE="no"
NFT_VERSION=""
if command -v nft >/dev/null 2>&1; then
  NFT_AVAILABLE="yes"
  NFT_VERSION=$(nft --version 2>/dev/null | head -n1 || echo "unknown")
fi

# Check for iptables binary and mode
IPTABLES_AVAILABLE="no"
IPTABLES_MODE="unknown"
IPTABLES_VERSION=""
if command -v iptables >/dev/null 2>&1; then
  IPTABLES_AVAILABLE="yes"
  version_line=$(iptables -V 2>/dev/null | head -n1 || echo "")
  IPTABLES_VERSION="$version_line"
  if printf '%s' "$version_line" | grep -qi 'nf_tables'; then
    IPTABLES_MODE="nf_tables"
  elif printf '%s' "$version_line" | grep -qi 'legacy'; then
    IPTABLES_MODE="legacy"
  fi
fi

# Determine validation status
VALIDATION_STATUS="ok"
VALIDATION_MESSAGE=""

if [[ "$CONFIGURED_MODE" == "nftables" ]]; then
  if [[ "$NFT_AVAILABLE" == "no" ]]; then
    VALIDATION_STATUS="error"
    VALIDATION_MESSAGE="nftables mode configured but nft binary not found in PATH"
  fi
elif [[ "$CONFIGURED_MODE" == "iptables" ]]; then
  if [[ "$IPTABLES_AVAILABLE" == "no" ]]; then
    VALIDATION_STATUS="error"
    VALIDATION_MESSAGE="iptables mode configured but iptables binary not found in PATH"
  elif [[ "$IPTABLES_MODE" != "legacy" ]]; then
    VALIDATION_STATUS="warning"
    VALIDATION_MESSAGE="iptables mode configured but iptables appears to be using nf_tables backend (expected legacy)"
  fi
elif [[ "$CONFIGURED_MODE" == "unknown" ]]; then
  VALIDATION_STATUS="warning"
  VALIDATION_MESSAGE="proxy mode not explicitly configured in $CONFIG_DIR"
fi

# Print diagnostic information
printf "Kube-proxy Dataplane Mode Validation\n"
printf "=====================================\n\n"
printf "Configuration:\n"
printf "  Config directory: %s\n" "$CONFIG_DIR"
printf "  Configured mode:  %s\n\n" "$CONFIGURED_MODE"

printf "Tool Availability:\n"
printf "  nft binary:       %s" "$NFT_AVAILABLE"
if [[ "$NFT_AVAILABLE" == "yes" ]]; then
  printf " (%s)" "$NFT_VERSION"
fi
printf "\n"
printf "  iptables binary:  %s" "$IPTABLES_AVAILABLE"
if [[ "$IPTABLES_AVAILABLE" == "yes" ]]; then
  printf " (mode: %s, version: %s)" "$IPTABLES_MODE" "$IPTABLES_VERSION"
fi
printf "\n\n"

printf "Validation Status: %s\n" "$VALIDATION_STATUS"
if [[ -n "$VALIDATION_MESSAGE" ]]; then
  printf "Message: %s\n" "$VALIDATION_MESSAGE"
fi

# Exit with appropriate code
if [[ "$VALIDATION_STATUS" == "error" ]]; then
  exit 1
elif [[ "$VALIDATION_STATUS" == "warning" ]]; then
  exit 2
else
  exit 0
fi
