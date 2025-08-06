#!/usr/bin/env bash
set -e

if [ $# -lt 1 ]; then
  echo "Usage: $0 <file.scad>" >&2
  exit 1
fi

FILE=$1
if [ ! -f "$FILE" ]; then
  echo "Error: $FILE not found" >&2
  exit 1
fi

base=$(basename "$FILE" .scad)
mode_suffix=""
if [ -n "$STANDOFF_MODE" ]; then
  mode_suffix="_$STANDOFF_MODE"
fi
output="stl/${base}${mode_suffix}.stl"
mkdir -p "$(dirname "$output")"
openscad -o "$output" --export-format binstl -D standoff_mode=\"${STANDOFF_MODE}\" "$FILE"
