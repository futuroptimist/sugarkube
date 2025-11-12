#!/usr/bin/env bash
set -euo pipefail

# Configure /etc/nsswitch.conf for mDNS resolution
# Idempotent: can be run multiple times safely

NSSWITCH_PATH="${NSSWITCH_PATH:-/etc/nsswitch.conf}"
DESIRED_HOSTS_LINE="hosts:          files mdns_minimal [NOTFOUND=return] resolve dns"

if [ ! -f "${NSSWITCH_PATH}" ]; then
    echo "nsswitch.conf not found at ${NSSWITCH_PATH}" >&2
    exit 1
fi

# Backup original if not already backed up
if [ ! -f "${NSSWITCH_PATH}.bak" ]; then
    cp "${NSSWITCH_PATH}" "${NSSWITCH_PATH}.bak"
fi

# Check if already configured correctly
if grep -Fxq "${DESIRED_HOSTS_LINE}" "${NSSWITCH_PATH}"; then
    echo "nsswitch.conf already configured for mDNS"
    exit 0
fi

# Update hosts line
python3 - <<'PY' "${NSSWITCH_PATH}" "${DESIRED_HOSTS_LINE}"
import sys
from pathlib import Path

nsswitch_path = Path(sys.argv[1])
desired_line = sys.argv[2]

lines = nsswitch_path.read_text(encoding="utf-8").splitlines()
new_lines = []
hosts_found = False

for line in lines:
    stripped = line.strip()
    if stripped.startswith("hosts:"):
        if not hosts_found:
            new_lines.append(desired_line)
            hosts_found = True
        # Skip any additional hosts: lines
    else:
        new_lines.append(line)

# If no hosts: line was found, add it
if not hosts_found:
    new_lines.append(desired_line)

content = "\n".join(new_lines) + "\n"
nsswitch_path.write_text(content, encoding="utf-8")
PY

echo "Updated ${NSSWITCH_PATH} with mDNS configuration"
