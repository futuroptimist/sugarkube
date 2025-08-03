# 🤖 AGENTS

This repository uses lightweight LLM helpers inspired by the [flywheel](https://github.com/futuroptimist/flywheel) project. It follows the [AGENTS.md spec](https://gist.github.com/dpaluy/cc42d59243b0999c1b3f9cf60dfd3be6) and [agentsmd.net](https://agentsmd.net/AGENTS.md).

The name **sugarkube** has two meanings:

1. The physical aluminium cube with solar panels that houses a Pi-based k3s
   cluster.
   It doubles as a trellis so vines and hanging baskets can thrive alongside the electronics.
2. "Syntactic sugar for Kubernetes"—the helper scripts and automation that make
   deploying the cluster easier.

## Code Linter Agent
- **When:** every PR
- **Does:** run `scripts/checks.sh` via pre-commit to lint, format and test.

## Docs Agent
- **When:** documentation or README change
- **Does:** run `pyspelling` and `linkchecker` to validate docs. This covers
  guides such as `docs/network_setup.md`.

## CAD Agent
- **When:** `.scad` files change
- **Does:**
  1. Render each SCAD in `heatset` and `printed` modes.
  2. Export `*.stl` meshes as workflow artifacts (not committed).
  3. Fail if compilation or regeneration fails.

## KiCad Agent
- **When:** KiCad schematic or PCB files change and on a weekly schedule
- **Does:** run the [KiBot action](https://github.com/INTI-CMNB/kibot) with `.kibot/power_ring.yaml` to export Gerbers, PDF schematics and BOM. The project
  requires **KiCad 9** so we use the `v2_k9` container tag.
- **Logs:** workflow logs are uploaded as artifacts so non-admins can download failure details.

### STL generation
STL meshes are not stored in the repository. The `scad-to-stl.yml` workflow renders them after each commit and exposes the files as downloadable artifacts.

### Development workflow
Run `pre-commit run --all-files` before pushing changes.
