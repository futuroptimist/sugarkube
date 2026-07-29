#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-}"
ENVIRONMENT="${2:-}"
DEST_ROOT="${SUGARKUBE_HEARTBEAT_ROOT:-}"
SYSTEMCTL="${SUGARKUBE_HEARTBEAT_SYSTEMCTL:-systemctl}"
TTY="/dev/tty"
[ -z "$DEST_ROOT" ] || TTY="${SUGARKUBE_HEARTBEAT_TEST_TTY:-/dev/tty}"
UNIT=sugarkube-healthchecks-heartbeat.service
TIMER=sugarkube-healthchecks-heartbeat.timer
credential_path="$DEST_ROOT/etc/sugarkube/healthchecks-url"
unit_dir="$DEST_ROOT/etc/systemd/system"
helper_dir="$DEST_ROOT/usr/local/lib/sugarkube"

die() { printf 'ERROR: %s\n' "$1" >&2; exit 2; }
[ "$ENVIRONMENT" = staging ] || die "host heartbeats require explicit env=staging; production and other environments are unsupported."
[ -n "$ACTION" ] || die "action is required."

for tool in hostname install mktemp mv rm; do
  command -v "$tool" >/dev/null 2>&1 || die "required tool '$tool' is unavailable."
done
[ "$ACTION" != install ] || command -v curl >/dev/null 2>&1 || die "required tool 'curl' is unavailable."
command -v "$SYSTEMCTL" >/dev/null 2>&1 || die "required tool 'systemctl' is unavailable."
hostname_value="$(hostname -s)" || die "hostname could not be resolved."
if ! awk 'NF && $1 !~ /^#/ {print $1}' "$ROOT/config/staging-nodes.txt" | grep -Fxq -- "$hostname_value"; then
  die "hostname '$hostname_value' is not in the canonical staging inventory."
fi

run_systemctl() { "$SYSTEMCTL" "$@"; }
install_assets() {
  install -d -m 0755 "$unit_dir" "$helper_dir"
  install -m 0644 "$ROOT/scripts/systemd/$UNIT" "$unit_dir/$UNIT"
  install -m 0644 "$ROOT/scripts/systemd/$TIMER" "$unit_dir/$TIMER"
  install -m 0755 "$ROOT/scripts/healthchecks_heartbeat.sh" "$helper_dir/healthchecks-heartbeat"
}
read_secret() {
  [ -t 0 ] || die "installation requires an interactive terminal; piped stdin is forbidden."
  [ -r "$TTY" ] && [ -w "$TTY" ] || die "a controlling terminal is required for silent credential entry."
  printf 'Enter this node\047s rotated Healthchecks.io ping URL (input hidden): ' >"$TTY"
  IFS= read -r -s secret <"$TTY" || die "credential input failed."
  printf '\n' >"$TTY"
  [ -n "$secret" ] || die "credential must not be empty."
  if ! printf '%s\n' "$secret" | "$ROOT/scripts/healthchecks_heartbeat.sh" --validate-stdin; then
    unset secret
    die "credential is invalid; expected one HTTPS Healthchecks UUID ping URL."
  fi
}
write_secret() {
  install -d -m 0755 "$(dirname "$credential_path")"
  tmp="$(mktemp "$(dirname "$credential_path")/.healthchecks-url.XXXXXX")" || die "credential staging failed."
  trap 'rm -f "$tmp"; unset secret' RETURN
  printf '%s\n' "$secret" >"$tmp"
  chmod 0600 "$tmp"
  if [ -z "$DEST_ROOT" ]; then chown root:root "$tmp"; fi
  mv -f "$tmp" "$credential_path"
  trap - RETURN; unset secret
}
facts() {
  printf 'hostname=%s\n' "$hostname_value"
  for path in "$credential_path" "$unit_dir/$UNIT" "$unit_dir/$TIMER" "$helper_dir/healthchecks-heartbeat"; do
    if [ -e "$path" ]; then
      printf 'asset=%s present owner=%s mode=%s\n' "${path#$DEST_ROOT}" \
        "$(stat -c %U:%G "$path")" "$(stat -c %a "$path")"
    else
      printf 'asset=%s missing\n' "${path#$DEST_ROOT}"
    fi
  done
  run_systemctl is-enabled "$TIMER" 2>/dev/null && printf 'timer_enabled=yes\n' || printf 'timer_enabled=no\n'
  run_systemctl is-active "$TIMER" 2>/dev/null && printf 'timer_active=yes\n' || printf 'timer_active=no\n'
  result="$(run_systemctl show "$UNIT" --property=Result --value 2>/dev/null || printf unknown)"
  case "$result" in success|failed|timeout|unknown|'') ;; *) result=unknown ;; esac
  printf 'last_unit_result=%s\nperiod=1min boot_delay=20s\n' "${result:-unknown}"
}

case "$ACTION" in
  install)
    [ -z "${HEALTHCHECKS_URL:-}" ] || die "credential environment variables are forbidden."
    [ "$(id -u)" -eq 0 ] || [ -n "$DEST_ROOT" ] || die "install must run as root."
    read_secret; install_assets; write_secret
    run_systemctl daemon-reload
    run_systemctl enable --now "$TIMER"
    printf 'Installed host heartbeat for %s; credential stored with mode 0600.\n' "$hostname_value"
    ;;
  status) facts ;;
  verify)
    run_systemctl is-enabled --quiet "$TIMER" || die "heartbeat timer is not enabled."
    run_systemctl start "$UNIT" || die "heartbeat unit failed; inspect sanitized journal metadata."
    deadline=$((SECONDS + 35))
    while [ "$SECONDS" -lt "$deadline" ]; do
      state="$(run_systemctl show "$UNIT" --property=ActiveState --value 2>/dev/null || true)"
      [ "$state" = activating ] || break
      sleep 1
    done
    [ "${state:-unknown}" = inactive ] || die "heartbeat verification did not finish within 35 seconds."
    [ "$(run_systemctl show "$UNIT" --property=Result --value 2>/dev/null || true)" = success ] || die "heartbeat verification failed."
    run_systemctl is-enabled --quiet "$TIMER" || die "heartbeat timer was not left enabled."
    printf 'Heartbeat verification succeeded for %s; recurring timer remains enabled.\n' "$hostname_value"
    ;;
  uninstall)
    [ "$(id -u)" -eq 0 ] || [ -n "$DEST_ROOT" ] || die "uninstall must run as root."
    [ -r "$TTY" ] && [ -w "$TTY" ] || die "a controlling terminal is required for uninstall confirmation."
    printf 'Type %s to remove the timer and local credential (destructive): ' "$hostname_value" >"$TTY"
    IFS= read -r confirmation <"$TTY" || die "confirmation input failed."
    [ "$confirmation" = "$hostname_value" ] || die "uninstall cancelled."
    run_systemctl disable --now "$TIMER" || true
    rm -f "$unit_dir/$UNIT" "$unit_dir/$TIMER" "$helper_dir/healthchecks-heartbeat" "$credential_path"
    rmdir "$helper_dir" "$(dirname "$credential_path")" 2>/dev/null || true
    run_systemctl daemon-reload
    printf 'Removed host heartbeat assets and local credential; remote Healthchecks.io and PagerDuty configuration was not changed.\n'
    ;;
  *) die "unknown action '$ACTION'." ;;
esac
