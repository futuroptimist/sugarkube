#!/usr/bin/env bash
set -euo pipefail

CONF="${AVAHI_CONF_PATH:-/etc/avahi/avahi-daemon.conf}"
FIX_REQUEST="${SUGARKUBE_FIX_AVAHI:-0}"

# Normalize fix flag
case "${FIX_REQUEST}" in
  1|true|TRUE|yes|YES|on|ON)
    FIX_REQUEST="1"
    ;;
  *)
    FIX_REQUEST="0"
    ;;
esac

STATUS_FILE="$(mktemp)"
cleanup() {
  rm -f "${STATUS_FILE}"
}
trap cleanup EXIT

python3 - "${CONF}" "${FIX_REQUEST}" "${STATUS_FILE}" <<'PY'
import os
import re
import sys
from pathlib import Path

conf_path = Path(sys.argv[1])
fix_requested = sys.argv[2] == "1"
status_path = Path(sys.argv[3])

suffix_pattern = re.compile(r"\.(?:IPv4|IPv6)$", re.IGNORECASE)

try:
    if not conf_path.exists():
        print("use_ipv4=")
        print("use_ipv6=")
        print("allow_interfaces=")
        print("deny_interfaces=")
        print("disable_publishing=")
        print("enable_dbus=")
        status_path.write_text("BAD_CONFIG=0", encoding="utf-8")
        sys.exit(0)

    text = conf_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    section = None
    use_ipv4 = None
    use_ipv6 = None
    allow_interfaces_raw = None
    allow_line_index = None
    deny_interfaces = None
    disable_publishing = None
    enable_dbus = None

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
            continue
        if "=" not in line:
            continue
        key_part, value_part = line.split("=", 1)
        key = key_part.strip().lower()
        value = value_part.strip()

        if key == "enable-dbus":
            enable_dbus = value
        if section != "server":
            continue
        if key == "use-ipv4":
            use_ipv4 = value
        elif key == "use-ipv6":
            use_ipv6 = value
        elif key == "allow-interfaces":
            allow_interfaces_raw = value
            allow_line_index = idx
        elif key == "deny-interfaces":
            deny_interfaces = value
        elif key == "disable-publishing":
            disable_publishing = value

    warnings = []
    bad_config = False
    modified = False

    sanitized_allow_value = allow_interfaces_raw
    suffix_tokens = []

    if allow_interfaces_raw is not None:
        tokens = [tok.strip() for tok in re.split(r"[\s,]+", allow_interfaces_raw) if tok.strip()]
        sanitized_tokens = []
        for token in tokens:
            sanitized = suffix_pattern.sub("", token)
            sanitized_tokens.append(sanitized)
            if sanitized != token:
                suffix_tokens.append(token)
        if suffix_tokens:
            warnings.append(
                "allow-interfaces includes IPv4/IPv6-specific suffixes: "
                + ", ".join(suffix_tokens)
            )
            if fix_requested and allow_line_index is not None:
                sanitized_allow_value = ",".join(sanitized_tokens)
                before, sep, after = lines[allow_line_index].partition("=")
                whitespace_match = re.match(r"\s*", after)
                spacing = whitespace_match.group(0) if whitespace_match else ""
                lines[allow_line_index] = f"{before}{sep}{spacing}{sanitized_allow_value}"
                modified = True
                print(
                    "INFO: stripped .IPv4/.IPv6 suffixes from allow-interfaces -> "
                    f"{sanitized_allow_value}",
                    file=sys.stderr,
                )
            else:
                bad_config = True
                warnings.append(
                    "Set SUGARKUBE_FIX_AVAHI=1 to automatically strip the suffixes "
                    "or edit allow-interfaces manually."
                )
        else:
            sanitized_allow_value = allow_interfaces_raw

    if disable_publishing and disable_publishing.lower() == "yes":
        warnings.append(
            "disable-publishing=yes prevents mDNS advertisement; set disable-publishing=no."
        )
        bad_config = True

    if enable_dbus and enable_dbus.lower() == "no":
        warnings.append(
            "enable-dbus=no disables Avahi's DBus interface; set enable-dbus=yes."
        )
        bad_config = True

    if (use_ipv4 and use_ipv4.lower() == "no") and (use_ipv6 and use_ipv6.lower() == "no"):
        warnings.append(
            "Both use-ipv4=no and use-ipv6=no are set; Avahi will not publish services."
        )
        bad_config = True

    for message in warnings:
        print(f"WARN: {message}", file=sys.stderr)

    if modified:
        conf_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        sanitized_allow_value = sanitized_allow_value or ""

    print(f"use_ipv4={use_ipv4 or ''}")
    print(f"use_ipv6={use_ipv6 or ''}")
    print(f"allow_interfaces={sanitized_allow_value or ''}")
    print(f"deny_interfaces={deny_interfaces or ''}")
    print(f"disable_publishing={disable_publishing or ''}")
    print(f"enable_dbus={enable_dbus or ''}")

    status_path.write_text(f"BAD_CONFIG={'1' if bad_config else '0'}", encoding="utf-8")
except Exception as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    status_path.write_text("BAD_CONFIG=1", encoding="utf-8")
    sys.exit(1)
PY

status=$?
if [ "${status}" -ne 0 ]; then
  exit "${status}"
fi

if [ -f "${STATUS_FILE}" ]; then
  result="$(cat "${STATUS_FILE}")"
  if [ "${result}" = "BAD_CONFIG=1" ]; then
    exit 2
  fi
fi

exit 0
