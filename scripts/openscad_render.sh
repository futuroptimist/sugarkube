#!/usr/bin/env bash
set -e

FILE=$1
if [ -z "$FILE" ]; then
  echo "Usage: $0 path/to/model.scad" >&2
  exit 1
fi
if [ ! -f "$FILE" ]; then
  echo "File not found: $FILE" >&2
  exit 1
fi

if ! command -v openscad >/dev/null 2>&1; then
  echo "OpenSCAD not found in PATH" >&2
  exit 1
fi

base=$(basename "$FILE" .scad)
mode_suffix=""
if [ -n "$STANDOFF_MODE" ]; then
  mode_suffix="_$STANDOFF_MODE"
fi
output="stl/${base}${mode_suffix}.stl"
mkdir -p "$(dirname "$output")"
cmd=(openscad -o "$output" --export-format binstl)
if [ -n "$STANDOFF_MODE" ]; then
  cmd+=(-D "standoff_mode=\"${STANDOFF_MODE}\"")
fi
cmd+=("$FILE")
"${cmd[@]}"
