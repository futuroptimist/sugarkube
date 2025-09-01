#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCAD="$ROOT/scad/mac_mini_station.scad"
mkdir -p "$ROOT/stl"
# Export full station
openscad -o "$ROOT/stl/mac_mini_station.stl" \
  -D PRINT_MAIN_STATION=true -D PRINT_SADDLE_CAP=false "$SCAD"
# Export saddle cap only
openscad -o "$ROOT/stl/saddle_cap_extension.stl" \
  -D PRINT_MAIN_STATION=false -D PRINT_SADDLE_CAP=true "$SCAD"
echo "STLs exported to ./stl"
