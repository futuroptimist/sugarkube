#!/usr/bin/env bash
# mdns_type_check.sh - Service type enumeration and fail-fast logic
# shellcheck disable=SC3040,SC3041,SC3043

mdns_selfcheck__service_type_check() {
  local type_output type_present available_types available_kv available_escaped available_seen
  local active_window_ms active_start_elapsed current_elapsed delta_ms remaining_ms sleep_seconds
  local active_output active_count active_found active_attempts

  type_output="$(run_command_capture mdns_browse_types avahi-browse --parsable --terminate _services._dns-sd._udp || true)"
  type_command="${MDNS_LAST_CMD_DISPLAY:-}"
  type_duration="${MDNS_LAST_CMD_DURATION_MS:-}"
  type_present=0
  available_types=""
  available_seen=","
  if [ -n "${type_output}" ]; then
    local old_ifs field browse_line
    old_ifs="${IFS}"
    while IFS= read -r browse_line; do
      [ -n "${browse_line}" ] || continue
      IFS=';'
      # shellcheck disable=SC2086
      set -- ${browse_line}
      IFS="${old_ifs}"
      for field in "$@"; do
        case "${field}" in
          "${SERVICE_TYPE}")
            type_present=1
            ;;&
          _*._tcp|_*._udp)
            case "${available_seen}" in
              *,"${field}",*)
                ;;
              *)
                available_seen="${available_seen}${field},"
                if [ -n "${available_types}" ]; then
                  available_types="${available_types},${field}"
                else
                  available_types="${field}"
                fi
                ;;
            esac
            ;;
        esac
      done
    done <<__MDNS_TYPES__
${type_output}
__MDNS_TYPES__
    IFS="${old_ifs}"
  fi

  case "${type_present}" in
    1) type_present=1 ;;
    *) type_present=0 ;;
  esac
  available_kv=""
  if [ -n "${available_types}" ]; then
    available_escaped="$(printf '%s' "${available_types}" | sed 's/"/\\"/g')"
    available_kv="available_types=\"${available_escaped}\""
  fi

  type_command_kv=""
  type_duration_kv=""
  if [ -n "${type_command}" ]; then
    type_command_kv="command=\"$(kv_escape "${type_command}")\""
  fi
  if [ -n "${type_duration}" ]; then
    type_duration_kv="command_duration_ms=${type_duration}"
  fi

  if [ "${type_present}" -eq 1 ]; then
    if [ -n "${available_kv}" ] && [ -n "${type_command_kv}" ] && [ -n "${type_duration_kv}" ]; then
      log_debug mdns_selfcheck event=mdns_type_check \
        present="${type_present}" \
        service_type="${SERVICE_TYPE}" \
        "${available_kv}" \
        "${type_command_kv}" \
        "${type_duration_kv}"
    elif [ -n "${available_kv}" ] && [ -n "${type_command_kv}" ]; then
      log_debug mdns_selfcheck event=mdns_type_check \
        present="${type_present}" \
        service_type="${SERVICE_TYPE}" \
        "${available_kv}" \
        "${type_command_kv}"
    elif [ -n "${available_kv}" ] && [ -n "${type_duration_kv}" ]; then
      log_debug mdns_selfcheck event=mdns_type_check \
        present="${type_present}" \
        service_type="${SERVICE_TYPE}" \
        "${available_kv}" \
        "${type_duration_kv}"
    elif [ -n "${available_kv}" ]; then
      log_debug mdns_selfcheck event=mdns_type_check \
        present="${type_present}" \
        service_type="${SERVICE_TYPE}" \
        "${available_kv}"
    elif [ -n "${type_command_kv}" ] && [ -n "${type_duration_kv}" ]; then
      log_debug mdns_selfcheck event=mdns_type_check \
        present="${type_present}" \
        service_type="${SERVICE_TYPE}" \
        "${type_command_kv}" \
        "${type_duration_kv}"
    elif [ -n "${type_command_kv}" ]; then
      log_debug mdns_selfcheck event=mdns_type_check \
        present="${type_present}" \
        service_type="${SERVICE_TYPE}" \
        "${type_command_kv}"
    elif [ -n "${type_duration_kv}" ]; then
      log_debug mdns_selfcheck event=mdns_type_check \
        present="${type_present}" \
        service_type="${SERVICE_TYPE}" \
        "${type_duration_kv}"
    else
      log_debug mdns_selfcheck event=mdns_type_check \
        present="${type_present}" \
        service_type="${SERVICE_TYPE}"
    fi
  else
    if [ -n "${available_kv}" ] && [ -n "${type_command_kv}" ] && [ -n "${type_duration_kv}" ]; then
      log_info mdns_type_check present="${type_present}" service_type="${SERVICE_TYPE}" severity=warn \
        "${available_kv}" \
        "${type_command_kv}" \
        "${type_duration_kv}"
    elif [ -n "${available_kv}" ] && [ -n "${type_command_kv}" ]; then
      log_info mdns_type_check present="${type_present}" service_type="${SERVICE_TYPE}" severity=warn \
        "${available_kv}" \
        "${type_command_kv}"
    elif [ -n "${available_kv}" ] && [ -n "${type_duration_kv}" ]; then
      log_info mdns_type_check present="${type_present}" service_type="${SERVICE_TYPE}" severity=warn \
        "${available_kv}" \
        "${type_duration_kv}"
    elif [ -n "${available_kv}" ]; then
      log_info mdns_type_check present="${type_present}" service_type="${SERVICE_TYPE}" severity=warn \
        "${available_kv}"
    elif [ -n "${type_command_kv}" ] && [ -n "${type_duration_kv}" ]; then
      log_info mdns_type_check present="${type_present}" service_type="${SERVICE_TYPE}" severity=warn \
        "${type_command_kv}" \
        "${type_duration_kv}"
    elif [ -n "${type_command_kv}" ]; then
      log_info mdns_type_check present="${type_present}" service_type="${SERVICE_TYPE}" severity=warn \
        "${type_command_kv}"
    elif [ -n "${type_duration_kv}" ]; then
      log_info mdns_type_check present="${type_present}" service_type="${SERVICE_TYPE}" severity=warn \
        "${type_duration_kv}"
    else
      log_info mdns_type_check present="${type_present}" service_type="${SERVICE_TYPE}" severity=warn
    fi
  fi

  active_window_ms="${ACTIVE_QUERY_WINDOW_MS}"
  case "${active_window_ms}" in
    ''|*[!0-9]*) active_window_ms=0 ;;
  esac

  active_start_elapsed="$(elapsed_since_start_ms "${script_start_ms}")"
  case "${active_start_elapsed}" in
    ''|*[!0-9]*) active_start_elapsed=0 ;;
  esac

  active_attempts=0
  active_found=0
  INITIAL_BROWSE_OUTPUT=""
  INITIAL_BROWSE_READY=0

  if [ "${type_present}" -eq 0 ]; then
    while :; do
      active_attempts=$((active_attempts + 1))
      active_output="$(run_command_capture mdns_browse_active avahi-browse --parsable --resolve --terminate "${SERVICE_TYPE}" || true)"
      active_command="${MDNS_LAST_CMD_DISPLAY:-}"
      active_duration="${MDNS_LAST_CMD_DURATION_MS:-}"
      active_count="$(printf '%s\n' "${active_output}" | awk -v svc="${SERVICE_TYPE}" '
BEGIN { FS = ";"; count = 0 }
$1 == "=" {
  for (i = 1; i <= NF; i++) {
    if ($i == svc) {
      count++
      break
    }
  }
}
END { print count }
"' 2>/dev/null | tr -d '\n' | tr -d '\r')"
      case "${active_count}" in
        ''|*[!0-9]*) active_count=0 ;;
      esac

      if [ "${active_count}" -gt 0 ]; then
        INITIAL_BROWSE_OUTPUT="${active_output}"
        INITIAL_BROWSE_READY=1
        active_found=1
        log_debug mdns_selfcheck event=mdns_type_active outcome=hit attempts="${active_attempts}" instances="${active_count}"
        break
      fi

      if [ "${active_window_ms}" -le 0 ]; then
        INITIAL_BROWSE_OUTPUT="${active_output}"
        break
      fi

      current_elapsed="$(elapsed_since_start_ms "${script_start_ms}")"
      case "${current_elapsed}" in
        ''|*[!0-9]*) current_elapsed=0 ;;
      esac
      delta_ms=$((current_elapsed - active_start_elapsed))
      if [ "${delta_ms}" -lt 0 ]; then
        delta_ms=0
      fi
      if [ "${delta_ms}" -ge "${active_window_ms}" ]; then
        INITIAL_BROWSE_OUTPUT="${active_output}"
        break
      fi

      remaining_ms=$((active_window_ms - delta_ms))
      if [ "${remaining_ms}" -le 0 ]; then
        break
      fi

      if [ "${remaining_ms}" -gt 1000 ]; then
        sleep_seconds=1
      else
        sleep_seconds="$({
          python3 - <<'PY' "${remaining_ms}"
import sys
try:
    delay = int(sys.argv[1])
except ValueError:
    delay = 0
print('{:.3f}'.format(delay / 1000.0))
PY
        } 2>/dev/null)"
        if [ -z "${sleep_seconds}" ]; then
          sleep_seconds=0
        fi
        case "${sleep_seconds}" in
          0|0.0|0.00|0.000) sleep_seconds=0 ;;
        esac
      fi

      if [ "${sleep_seconds}" = "0" ] || [ -z "${sleep_seconds}" ]; then
        sleep 1
      else
        sleep "${sleep_seconds}"
      fi
    done

    if [ "${active_found}" -ne 1 ]; then
      elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
      case "${elapsed_ms}" in
        ''|*[!0-9]*) elapsed_ms=0 ;;
      esac
      active_command_kv=""
      active_duration_kv=""
      if [ -n "${active_command}" ]; then
        active_command_kv="command=\"$(kv_escape "${active_command}")\""
      fi
      if [ -n "${active_duration}" ]; then
        active_duration_kv="command_duration_ms=${active_duration}"
      fi
      if [ -n "${active_command_kv}" ] && [ -n "${active_duration_kv}" ]; then
        log_debug mdns_selfcheck event=mdns_type_active outcome=miss service_type="${SERVICE_TYPE}" attempts="${active_attempts}" ms_elapsed="${elapsed_ms}" "${active_command_kv}" "${active_duration_kv}"
      elif [ -n "${active_command_kv}" ]; then
        log_debug mdns_selfcheck event=mdns_type_active outcome=miss service_type="${SERVICE_TYPE}" attempts="${active_attempts}" ms_elapsed="${elapsed_ms}" "${active_command_kv}"
      elif [ -n "${active_duration_kv}" ]; then
        log_debug mdns_selfcheck event=mdns_type_active outcome=miss service_type="${SERVICE_TYPE}" attempts="${active_attempts}" ms_elapsed="${elapsed_ms}" "${active_duration_kv}"
      else
        log_debug mdns_selfcheck event=mdns_type_active outcome=miss service_type="${SERVICE_TYPE}" attempts="${active_attempts}" ms_elapsed="${elapsed_ms}"
      fi
    fi
  fi
  
  # Fail fast with exit code 4 when service type is missing
  # This check is after the function completes to ensure we tried both
  # initial enumeration and active query window
  if [ "${type_present}" -eq 0 ] && [ "${active_found}" -eq 0 ]; then
    elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
    case "${elapsed_ms}" in
      ''|*[!0-9]*) elapsed_ms=0 ;;
    esac
    
    if [ -n "${type_command_kv}" ] && [ -n "${type_duration_kv}" ] && [ -n "${available_kv}" ]; then
      log_info mdns_selfcheck outcome=fail reason=service_type_missing service_type="${SERVICE_TYPE}" ms_elapsed="${elapsed_ms}" "${available_kv}" "${type_command_kv}" "${type_duration_kv}"
    elif [ -n "${type_command_kv}" ] && [ -n "${available_kv}" ]; then
      log_info mdns_selfcheck outcome=fail reason=service_type_missing service_type="${SERVICE_TYPE}" ms_elapsed="${elapsed_ms}" "${available_kv}" "${type_command_kv}"
    elif [ -n "${type_duration_kv}" ] && [ -n "${available_kv}" ]; then
      log_info mdns_selfcheck outcome=fail reason=service_type_missing service_type="${SERVICE_TYPE}" ms_elapsed="${elapsed_ms}" "${available_kv}" "${type_duration_kv}"
    elif [ -n "${available_kv}" ]; then
      log_info mdns_selfcheck outcome=fail reason=service_type_missing service_type="${SERVICE_TYPE}" ms_elapsed="${elapsed_ms}" "${available_kv}"
    elif [ -n "${type_command_kv}" ] && [ -n "${type_duration_kv}" ]; then
      log_info mdns_selfcheck outcome=fail reason=service_type_missing service_type="${SERVICE_TYPE}" ms_elapsed="${elapsed_ms}" "${type_command_kv}" "${type_duration_kv}"
    elif [ -n "${type_command_kv}" ]; then
      log_info mdns_selfcheck outcome=fail reason=service_type_missing service_type="${SERVICE_TYPE}" ms_elapsed="${elapsed_ms}" "${type_command_kv}"
    elif [ -n "${type_duration_kv}" ]; then
      log_info mdns_selfcheck outcome=fail reason=service_type_missing service_type="${SERVICE_TYPE}" ms_elapsed="${elapsed_ms}" "${type_duration_kv}"
    else
      log_info mdns_selfcheck outcome=fail reason=service_type_missing service_type="${SERVICE_TYPE}" ms_elapsed="${elapsed_ms}"
    fi
    exit 4
  fi
}
