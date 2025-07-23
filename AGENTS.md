# 🤖 AGENTS

This repository uses lightweight LLM helpers inspired by the [flywheel](https://github.com/futuroptimist/flywheel) project.

## Code Linter Agent
- **When:** every PR
- **Does:** run pre-commit checks via `scripts/checks.sh` and suggest fixes.

## Docs Agent
- **When:** docs or README change
- **Does:** spell-check and link-check documentation.

## CAD Agent

- **When:** any `.scad` file changes (push or PR).
- **Does:**
  1. Compiles every SCAD twice – once with `standoff_mode="heatset"` and once with `standoff_mode="printed"` – ensuring both variants render without errors (see `tests/cad_regress_test.py`).
  2. Automatically regenerates the matching `*.stl` meshes via the `Build and Commit STL` workflow and pushes them back if they differ.
  3. Fails the run if compilation or regeneration fails, preventing broken geometry from being merged.

### STL merge safety

STL files are treated as binary artefacts. A root‐level `.gitattributes` file marks `*.stl` as `merge=ours`; this prevents interactive merge conflicts by favouring the current branch’s copy and letting CI regenerate clean meshes on the resulting commit.

Before pushing changes run `pre-commit run --all-files`.
