# 🍧 sugarkube

[![Docs](https://img.shields.io/github/actions/workflow/status/futuroptimist/sugarkube/.github/workflows/docs.yml?label=docs)](https://github.com/futuroptimist/sugarkube/actions/workflows/docs.yml)
[![Spellcheck](https://img.shields.io/github/actions/workflow/status/futuroptimist/sugarkube/.github/workflows/spellcheck.yml?label=spellcheck)](https://github.com/futuroptimist/sugarkube/actions/workflows/spellcheck.yml)
[![KiCad](https://img.shields.io/github/actions/workflow/status/futuroptimist/sugarkube/.github/workflows/kicad-export.yml?label=kicad)](https://github.com/futuroptimist/sugarkube/actions/workflows/kicad-export.yml)
[![STL](https://img.shields.io/github/actions/workflow/status/futuroptimist/sugarkube/.github/workflows/scad-to-stl.yml?label=stl)](https://github.com/futuroptimist/sugarkube/actions/workflows/scad-to-stl.yml)
[![License](https://img.shields.io/github/license/futuroptimist/sugarkube)](LICENSE)

An accessible k3s platform for Raspberry Pis and other SBCs integrated with an off-grid solar setup.  This repository also documents the solar cube art installation for powering aquarium air pumps and small computers.

## Repository layout

- `cad/` — OpenSCAD models of structural parts.  See `docs/pi_cluster_carrier.md` for the Pi carrier plate.
- `stl/` — generated STL files (via GitHub Actions)
- `elex/` — KiCad and Fritzing electronics schematics
- `docs/` — build instructions and safety notes
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

STL files are produced automatically by CI for each OpenSCAD model. To render
a variant locally you can run:

```bash
STANDOFF_MODE=heatset bash scripts/openscad_render.sh cad/pi_cluster/pi5_triple_carrier_rot45.scad
```

See [AGENTS.md](AGENTS.md) for included LLM assistants.
