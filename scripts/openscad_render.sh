#!/usr/bin/env bash
set -e

FILE=$1
output="stl/$(basename "$FILE" .scad).stl"
mkdir -p "$(dirname "$output")"
openscad -o "$output" --export-format binstl "$FILE"
