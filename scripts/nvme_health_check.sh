#!/usr/bin/env bash
#
# Collect NVMe SMART metrics and raise alerts when thresholds are exceeded.
#
# The helper mirrors docs/nvme-health-check.md so automation no longer needs to
# copy the reference script by hand. Thresholds can be customised via
# environment variables or CLI flags. When a limit is exceeded the script exits
# non-zero so schedulers (cron, systemd timers) can surface alerts.

set -euo pipefail
IFS=$'\n\t'

DEVICE=${NVME_DEVICE:-/dev/nvme0n1}
PCT_THRESH=${NVME_PCT_THRESH:-80}
TBW_LIMIT=${NVME_TBW_LIMIT_TB:-300}
MEDIA_ERR_THRESH=${NVME_MEDIA_ERR_THRESH:-0}
UNSAFE_SHUT_THRESH=${NVME_UNSAFE_SHUT_THRESH:-5}
LOGGER_TAG=${NVME_LOGGER_TAG:-nvme-health}

usage() {
  cat <<'USAGE'
Usage: nvme_health_check.sh [options]

Options override the matching environment variables:
  --device PATH                 NVMe namespace to inspect (default: /dev/nvme0n1)
  --pct-thresh VALUE            Percentage used threshold that triggers an alert (default: 80)
  --tbw-limit VALUE             Terabytes written threshold (default: 300)
  --media-errors VALUE          Media error threshold (default: 0)
  --unsafe-shutdowns VALUE      Unsafe shutdown threshold (default: 5)
  --logger-tag TAG              Custom syslog tag (default: nvme-health)
  -h, --help                    Show this help text and exit

Environment variables mirror the flag names (NVME_DEVICE, NVME_PCT_THRESH, ...).
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device)
      DEVICE="$2"
      shift 2
      ;;
    --pct-thresh)
      PCT_THRESH="$2"
      shift 2
      ;;
    --tbw-limit)
      TBW_LIMIT="$2"
      shift 2
      ;;
    --media-errors)
      MEDIA_ERR_THRESH="$2"
      shift 2
      ;;
    --unsafe-shutdowns)
      UNSAFE_SHUT_THRESH="$2"
      shift 2
      ;;
    --logger-tag)
      LOGGER_TAG="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! command -v nvme >/dev/null 2>&1; then
  echo "nvme CLI not found. Install nvme-cli before running this helper." >&2
  exit 1
fi

if ! command -v bc >/dev/null 2>&1; then
  echo "bc utility not found. Install bc to enable floating point comparisons." >&2
  exit 1
fi

log() {
  local message="$1"
  if command -v logger >/dev/null 2>&1; then
    logger -t "$LOGGER_TAG" "$message"
  fi
  printf '%s\n' "$message"
}

smart_json=$(nvme smart-log "$DEVICE" | tr -d '\r')

get_field() {
  local key="$1"
  awk -F ':' -v key="$key" '$1 ~ key { gsub(/ /, "", $2); print $2 }' <<<"$smart_json"
}

critical_warning=$(get_field "critical_warning")
percentage_used=$(get_field "percentage_used")
data_units_written=$(get_field "data_units_written")
media_errors=$(get_field "media_errors")
unsafe_shutdowns=$(get_field "unsafe_shutdowns")

percentage_used="${percentage_used%%%}"

tbw=$(awk -v duw="$data_units_written" 'BEGIN { printf "%.2f", duw * 512000 / 1e12 }')

status=0

if [[ -z "$critical_warning" || -z "$percentage_used" || -z "$tbw" ]]; then
  log "Failed to parse NVMe SMART output for $DEVICE"
  exit 1
fi

summary="NVMe health check: device=$DEVICE pct=${percentage_used}% tbw=${tbw}TB"
summary+=" warnings=${critical_warning} media=${media_errors} unsafe=${unsafe_shutdowns}"

if [[ "$critical_warning" != "0x00" ]]; then
  log "CRITICAL warning flag set: $critical_warning"
  status=1
fi

if (( percentage_used >= PCT_THRESH )); then
  log "Wear level ${percentage_used}% exceeds threshold ${PCT_THRESH}%"
  status=1
fi

if (( $(echo "$tbw >= $TBW_LIMIT" | bc -l) )); then
  log "Total bytes written ${tbw}TB exceeds ${TBW_LIMIT}TB"
  status=1
fi

if (( media_errors > MEDIA_ERR_THRESH )); then
  log "Media errors ${media_errors} exceed ${MEDIA_ERR_THRESH}"
  status=1
fi

if (( unsafe_shutdowns > UNSAFE_SHUT_THRESH )); then
  log "Unsafe shutdowns ${unsafe_shutdowns} exceed ${UNSAFE_SHUT_THRESH}"
  status=1
fi

log "$summary"
exit $status
