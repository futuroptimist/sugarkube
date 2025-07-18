#!/usr/bin/env bash
set -e

FILE=$1
base=$(basename "$FILE" .scad)
mode_suffix=""
if [ -n "$STANDOFF_MODE" ]; then
  mode_suffix="_$STANDOFF_MODE"
fi
output="stl/${base}${mode_suffix}.stl"
mkdir -p "$(dirname "$output")"
openscad -o "$output" --export-format binstl -D standoff_mode=\"${STANDOFF_MODE}\" "$FILE"
