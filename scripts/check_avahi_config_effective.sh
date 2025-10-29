#!/usr/bin/env bash
set -euo pipefail

CONF_PATH="${AVAHI_CONF_PATH:-/etc/avahi/avahi-daemon.conf}"
FIX_MODE="${SUGARKUBE_FIX_AVAHI:-0}"

python3 - "$CONF_PATH" "$FIX_MODE" <<'PY'
import re
import sys
from pathlib import Path

CONF_PATH = Path(sys.argv[1])
FIX_MODE = sys.argv[2].lower() in {"1", "true", "yes", "on"}

try:
    if CONF_PATH.exists():
        content = CONF_PATH.read_text(encoding="utf-8")
    else:
        content = ""
except Exception as exc:
    print(f"warning=read_error|Unable to read {CONF_PATH}: {exc}")
    sys.exit(1)

lines = content.splitlines()
entries = {}
section = None

for raw_line in lines:
    stripped = raw_line.strip()
    if not stripped:
        continue
    if stripped.startswith("#") or stripped.startswith(";"):
        continue
    if stripped.startswith("[") and stripped.endswith("]"):
        section = stripped[1:-1].strip().lower()
        continue
    if "=" not in stripped:
        continue
    key, value = stripped.split("=", 1)
    key = key.strip().lower()
    value = value.strip()
    entries[(section or ""), key] = value
    # Also store last occurrence regardless of section for quick lookup
    entries[(None, key)] = value

allow_value = entries.get((None, "allow-interfaces"), "")
deny_value = entries.get((None, "deny-interfaces"), "")
use_ipv4 = entries.get((None, "use-ipv4"), "")
use_ipv6 = entries.get((None, "use-ipv6"), "")
disable_publishing = entries.get((None, "disable-publishing"), "")
enable_dbus = entries.get((None, "enable-dbus"), "")

allow_value_clean = allow_value.strip()
allow_suffix_pattern = re.compile(r"\.(?:ipv4|ipv6)(?=[\s,]|$)", re.IGNORECASE)
allow_has_suffix = bool(allow_suffix_pattern.search(allow_value_clean))
cleaned_allow_value = allow_suffix_pattern.sub("", allow_value_clean)

warnings = []
fix_applied = []

if allow_has_suffix:
    warnings.append((
        "allow_interfaces_suffix",
        'allow-interfaces includes deprecated ".IPv4"/".IPv6" suffixes'
    ))

    if FIX_MODE and CONF_PATH.exists():
        updated_lines = []
        pattern = re.compile(r"^(\s*allow-interfaces\s*=)(.*)$", re.IGNORECASE)
        changed = False
        for raw_line in lines:
            match = pattern.match(raw_line)
            if match:
                prefix, current_value = match.groups()
                new_value = allow_suffix_pattern.sub("", current_value.strip())
                # Preserve original spacing before value but normalise trailing spaces
                updated_line = f"{prefix}{new_value}"
                if new_value != current_value.strip():
                    changed = True
                updated_lines.append(updated_line)
            else:
                updated_lines.append(raw_line)
        if changed:
            try:
                CONF_PATH.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
                fix_applied.append("allow_interfaces_suffix")
                allow_value_clean = cleaned_allow_value
            except Exception as exc:
                warnings.append((
                    "allow_interfaces_fix_failed",
                    f"Failed to apply auto-fix for allow-interfaces: {exc}"
                ))
        else:
            # No change needed (e.g. already stripped but matched earlier)
            allow_value_clean = cleaned_allow_value
    else:
        allow_value_clean = cleaned_allow_value

if disable_publishing.lower() == "yes":
    warnings.append((
        "disable_publishing",
        "disable-publishing is set to yes; Avahi will not publish services"
    ))

if enable_dbus.lower() == "no":
    warnings.append((
        "dbus_disabled",
        "enable-dbus is set to no; Avahi D-Bus integration disabled"
    ))

if use_ipv4.lower() == "no" and use_ipv6.lower() == "no":
    warnings.append((
        "protocols_disabled",
        "Both use-ipv4 and use-ipv6 are set to no; mDNS is disabled"
    ))

print(f"use_ipv4={use_ipv4}")
print(f"use_ipv6={use_ipv6}")
print(f"allow_interfaces={allow_value_clean}")
print(f"deny_interfaces={deny_value}")
print(f"disable_publishing={disable_publishing}")
print(f"enable_dbus={enable_dbus}")

for code, message in warnings:
    safe_message = message.replace("\n", " ").strip()
    print(f"warning={code}|{safe_message}")

for code in fix_applied:
    print(f"fix_applied={code}")
PY
