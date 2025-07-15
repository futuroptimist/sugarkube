#!/usr/bin/env bash
set -e

PROJECT=$1
mkdir -p kicad-export
kicad-cli pcb export gerbers "$PROJECT" -o kicad-export/gerbers
kicad-cli sch export pdf "$PROJECT" -o kicad-export/
