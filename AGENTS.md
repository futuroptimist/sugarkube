# 🤖 AGENTS

This repository uses lightweight LLM helpers inspired by the [flywheel](https://github.com/futuroptimist/flywheel) project. It follows the [AGENTS.md spec](https://gist.github.com/dpaluy/cc42d59243b0999c1b3f9cf60dfd3be6) and [agentsmd.net](https://agentsmd.net/AGENTS.md).

## Code Linter Agent
- **When:** every PR
- **Does:** run `scripts/checks.sh` via pre-commit to lint, format and test.

## Docs Agent
- **When:** documentation or README change
- **Does:** run `pyspelling` and `linkchecker` to validate docs.

## CAD Agent
- **When:** `.scad` files change
- **Does:**
  1. Render each SCAD in `heatset` and `printed` modes.
  2. Regenerate `*.stl` meshes and push them if changed.
  3. Fail if compilation or regeneration fails.

## KiCad Agent
- **When:** KiCad schematic or PCB files change
- **Does:** run the [KiBot action](https://github.com/INTI-CMNB/kibot) with `.kibot/power_ring.yaml` to export Gerbers, PDF schematics and BOM. The project
  requires **KiCad 9** so we use the `v2_k9` container tag.

### STL merge safety
STL files are treated as binary artefacts. `.gitattributes` marks them with `merge=ours` so merges remain conflict-free.

### Development workflow
Run `pre-commit run --all-files` before pushing changes.
