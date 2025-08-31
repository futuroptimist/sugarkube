---
title: 'Sugarkube CAD Prompt'
slug: 'prompts-codex-cad'
---

# Codex CAD Prompt

Use this prompt when 3D models need updating or verification.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository focused on 3D assets.

PURPOSE:
Keep OpenSCAD sources current and ensure they render cleanly.

CONTEXT:
- CAD files reside in [`cad/`](../cad/).
- Use [`scripts/openscad_render.sh`](../scripts/openscad_render.sh) to export STL meshes into
  [`stl/`](../stl/).
- The CI workflow [`scad-to-stl.yml`](../.github/workflows/scad-to-stl.yml) regenerates these models
  as artifacts. Do not commit `.stl` files.
- Render each model in both `heatset` and `printed` modes. Set `STANDOFF_MODE` (case-insensitive)
  to choose the mode; leaving it unset renders `heatset`.
- Follow [`AGENTS.md`](../AGENTS.md) and [`README.md`](../README.md) for repository conventions.
- Run `pre-commit run --all-files` after changes.
  For documentation updates, also run `pyspelling -c .spellcheck.yaml` (requires `aspell` and
  `aspell-en`) and `linkchecker --no-warnings README.md docs/`.
- Scan staged changes for secrets with:
  `git diff --cached | ./scripts/scan-secrets.py` before committing.
- Log tool failures in [`outages/`](../outages/) using
  [`outages/schema.json`](../outages/schema.json).

REQUEST:
1. Inspect `cad/*.scad` for todo comments or needed adjustments.
2. Modify geometry or parameters as required.
3. Render the model via:

   ```bash
   ./scripts/openscad_render.sh path/to/model.scad  # heatset by default
   STANDOFF_MODE=printed ./scripts/openscad_render.sh path/to/model.scad  # case-insensitive
   ```

4. Commit updated SCAD sources and any documentation.

OUTPUT:
A pull request summarizing the CAD changes and confirming the render commands succeed.
```

## Upgrade Prompt
Type: evergreen

Use this prompt to refine sugarkube's own prompt documentation.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.
Follow `AGENTS.md` and `README.md`.
Run `pre-commit run --all-files`, `pyspelling -c .spellcheck.yaml` (requires
`aspell` and `aspell-en`), `linkchecker --no-warnings README.md docs/`, and
`git diff --cached | ./scripts/scan-secrets.py` before committing.

USER:
1. Pick one prompt doc under `docs/` (for example, `prompts-codex-cad.md`).
2. Fix outdated instructions, links, or formatting.
3. Run the commands above.

OUTPUT:
A pull request with the improved prompt doc and passing checks.
```
