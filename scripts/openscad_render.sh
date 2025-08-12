#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 path/to/model.scad" >&2
  exit 1
fi

FILE=$1
if [ ! -f "$FILE" ]; then
  echo "File not found: $FILE" >&2
  exit 1
fi

if [[ "$FILE" != *.scad ]]; then
  echo "Expected .scad file: $FILE" >&2
  exit 1
fi

base=$(basename "$FILE" .scad)
mode_suffix=""
if [ -n "${STANDOFF_MODE:-}" ]; then
  case "$STANDOFF_MODE" in
    heatset|printed)
      mode_suffix="_$STANDOFF_MODE"
      ;;
    *)
      echo "Invalid STANDOFF_MODE: $STANDOFF_MODE (expected 'heatset' or 'printed')" >&2
      exit 1
      ;;
  esac
fi

if ! command -v openscad >/dev/null 2>&1; then
  echo "OpenSCAD not found in PATH" >&2
  exit 1
fi
output="stl/${base}${mode_suffix}.stl"
mkdir -p "$(dirname "$output")"
cmd=(openscad -o "$output" --export-format binstl)
if [ -n "${STANDOFF_MODE:-}" ]; then
  cmd+=(-D "standoff_mode=\"${STANDOFF_MODE}\"")
fi
cmd+=("$FILE")
"${cmd[@]}"
