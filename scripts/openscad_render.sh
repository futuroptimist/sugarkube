#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $(basename "$0") path/to/model.scad" >&2
  exit 1
fi

FILE=$1
if [ ! -f "$FILE" ]; then
  echo "File not found: $FILE" >&2
  exit 1
fi
ext="${FILE##*.}"
# Pattern match for extension to support Bash 3 without `${var,,}`
case "$ext" in
  [Ss][Cc][Aa][Dd]) ;;
  *)
    echo "Expected .scad file: $FILE" >&2
    exit 1
    ;;
esac

base=$(basename -- "$FILE" ".$ext")
mode_suffix=""
standoff_mode=""
if [ -n "${STANDOFF_MODE:-}" ]; then
  # Trim and normalize without Bash 4 string lowering
  standoff_mode="$(printf '%s' "$STANDOFF_MODE" | xargs)"
  if [ -n "$standoff_mode" ]; then
    case "$standoff_mode" in
      [Hh][Ee][Aa][Tt][Ss][Ee][Tt])
        standoff_mode="heatset"
        mode_suffix="_heatset"
        ;;
      [Pp][Rr][Ii][Nn][Tt][Ee][Dd])
        standoff_mode="printed"
        mode_suffix="_printed"
        ;;
      [Nn][Uu][Tt])
        standoff_mode="nut"
        mode_suffix="_nut"
        ;;
      *)
        echo "Invalid STANDOFF_MODE: $STANDOFF_MODE (expected 'heatset', 'printed', or 'nut')" >&2
        exit 1
        ;;
    esac
  fi
fi

if ! command -v openscad >/dev/null 2>&1; then
  echo "OpenSCAD not found in PATH" >&2
  exit 1
fi
output="stl/${base}${mode_suffix}.stl"
mkdir -p "$(dirname "$output")"
cmd=(openscad -o "$output" --export-format binstl)
if [ -n "$standoff_mode" ]; then
  cmd+=(-D "standoff_mode=\"${standoff_mode}\"")
fi
cmd+=(-- "$FILE")
"${cmd[@]}"
