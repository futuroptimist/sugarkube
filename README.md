# sugarkube

An accessible k3s platform for Raspberry Pis and other SBCs integrated with an off-grid solar setup.  This repository also documents the solar cube art installation for powering aquarium air pumps and small computers.

## Repository layout

- `cad/` — OpenSCAD models of structural parts.  See `docs/pi_cluster_carrier.md` for the Pi carrier plate.
- `stl/` — generated STL files (via GitHub Actions)
- `elex/` — KiCad and Fritzing electronics schematics
- `docs/` — build instructions and safety notes
- `scripts/` — helper scripts for rendering and exports

Run `pre-commit run --all-files` before committing.

STL files are produced automatically by CI for each OpenSCAD model. To render
a variant locally you can run:

```bash
STANDOFF_MODE=heatset bash scripts/openscad_render.sh cad/pi_cluster/pi5_triple_carrier_rot45.scad
```
