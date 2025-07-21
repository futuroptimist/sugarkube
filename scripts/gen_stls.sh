#!/usr/bin/env bash
set -e

modes=(heatset printed)
mkdir -p stl
for mode in "${modes[@]}"; do
  export STANDOFF_MODE="$mode"
  find cad -name '*.scad' -print0 | xargs -0 -I{} bash scripts/openscad_render.sh "{}"
  unset STANDOFF_MODE
done
