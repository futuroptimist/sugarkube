#!/usr/bin/env bash
set -e

PROJECT=$1
mkdir -p kicad-export
kicad-cli pcb export gerbers "$PROJECT" -o kicad-export/gerbers
SCH=${PROJECT%.kicad_pcb}.kicad_sch
kicad-cli sch export pdf "$SCH" -o kicad-export/
kicad-cli sch export bom "$SCH" -o kicad-export/bom.csv
