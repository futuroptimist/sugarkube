# 🍧 sugarkube

[![docs](https://github.com/futuroptimist/sugarkube/actions/workflows/docs.yml/badge.svg?branch=main)](https://github.com/futuroptimist/sugarkube/actions/workflows/docs.yml)
[![spellcheck](https://github.com/futuroptimist/sugarkube/actions/workflows/spellcheck.yml/badge.svg?branch=main)](https://github.com/futuroptimist/sugarkube/actions/workflows/spellcheck.yml)
[![kicad](https://github.com/futuroptimist/sugarkube/actions/workflows/kicad-export.yml/badge.svg?branch=main)](https://github.com/futuroptimist/sugarkube/actions/workflows/kicad-export.yml)
[![stl](https://github.com/futuroptimist/sugarkube/actions/workflows/scad-to-stl.yml/badge.svg?branch=main)](https://github.com/futuroptimist/sugarkube/actions/workflows/scad-to-stl.yml)
[![Coverage](https://codecov.io/gh/futuroptimist/sugarkube/branch/main/graph/badge.svg)](https://codecov.io/gh/futuroptimist/sugarkube)
[![license](https://img.shields.io/github/license/futuroptimist/sugarkube)](LICENSE)

An accessible k3s platform for Raspberry Pis and other SBCs integrated with an off-grid solar setup.  This repository also documents the solar cube art installation for powering aquarium air pumps and small computers.
The cube also doubles as a living trellis. Climbing plants weave through the aluminium extrusion while shade-loving herbs thrive beneath the panels. Hanging baskets can clip onto the frame so the installation is surrounded by greenery.

### What's in a name?

"Sugarkube" refers to both the aluminium cube covered in solar panels **and**
the helper scripts that provide "syntactic sugar" for Kubernetes.  Throughout
the docs you will see the term used in both contexts.

## Repository layout

- `cad/` — OpenSCAD models of structural parts.  See `docs/pi_cluster_carrier.md` for the Pi carrier plate.
- `elex/` — KiCad and Fritzing electronics schematics including the `power_ring` board (see `elex/power_ring/specs.md`)
- `docs/` — build instructions, safety notes, and learning resources
- `docs/solar_basics.md` — introduction to how solar panels generate power
- `docs/electronics_basics.md` — essential circuits and tools
- `docs/power_system_design.md` — sizing batteries and charge controllers
- `docs/insert_basics.md` — guide for heat-set inserts and printed threads
- `docs/network_setup.md` — connect the Pi cluster to your network
- `docs/lcd_mount.md` — optional 1602 LCD standoff locations
- `scripts/` — helper scripts for rendering and exports

Run `pre-commit run --all-files` before committing.

## Getting Started

```bash
git clone git@github.com:futuroptimist/sugarkube.git
cd sugarkube
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

STL files are produced automatically by CI for each OpenSCAD model and can be
downloaded from the workflow run. To render a variant locally you can run:

```bash
STANDOFF_MODE=heatset bash scripts/openscad_render.sh cad/pi_cluster/pi5_triple_carrier_rot45.scad
```

See [AGENTS.md](AGENTS.md) for included LLM assistants.
See [llms.txt](llms.txt) for an overview suitable for language models.
