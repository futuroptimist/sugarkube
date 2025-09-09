---
title: 'Sugarkube Codex CAD Prompt'
slug: 'prompts-codex-cad'
---

# Sugarkube Codex CAD Prompt

Use this prompt to update or verify OpenSCAD models.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository focused on 3D assets.

PURPOSE:
Keep OpenSCAD models current and ensure they render cleanly.

CONTEXT:
- CAD files reside in [`cad/`](../cad/).
- Use [`scripts/openscad_render.sh`](../scripts/openscad_render.sh) to export binary STL meshes
  to the git-ignored [`stl/`](../stl/) directory. Ensure the `openscad` binary is installed and
  on `PATH`; the script exits early if it cannot find it.
- The GitHub workflow [`scad-to-stl.yml`](../.github/workflows/scad-to-stl.yml) regenerates the
  meshes as artifacts. Never commit `.stl` files.
- Render each model for all supported `standoff_mode` values (for example, `heatset`, `printed`,
  or `nut`). `STANDOFF_MODE` is optional, case-insensitive, trims surrounding whitespace, and
  defaults to the model’s `standoff_mode` value (usually `heatset`).
- Follow [`AGENTS.md`](../AGENTS.md) and [`README.md`](../README.md) for repository conventions.
- Run `pre-commit run --all-files` to invoke
  [`scripts/checks.sh`](../scripts/checks.sh) for linting, formatting, and tests.
- For documentation updates, also run:
  - `pyspelling -c .spellcheck.yaml` (requires `aspell` and `aspell-en`; see
    [`.spellcheck.yaml`](../.spellcheck.yaml))
  - `linkchecker --no-warnings README.md docs/` to verify links in
    [`README.md`](../README.md) and [`docs/`](../docs/)
- Scan staged changes for secrets with `git diff --cached | ./scripts/scan-secrets.py` before
  committing.
- Log tool failures in [`outages/`](../outages/) using
  [`outages/schema.json`](../outages/schema.json).

REQUEST:
1. Inspect `cad/*.scad` for todo comments or needed adjustments.
2. Modify geometry or parameters as required.
3. Render the model via (use `~~~` fences inside this prompt to avoid breaking the outer
   code block):
   ~~~bash
   ./scripts/openscad_render.sh path/to/model.scad  # uses default standoff_mode (heatset)
   STANDOFF_MODE=printed ./scripts/openscad_render.sh path/to/model.scad  # case-insensitive
   STANDOFF_MODE=nut ./scripts/openscad_render.sh path/to/model.scad
   ~~~

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
Follow [`AGENTS.md`](../AGENTS.md) and [`README.md`](../README.md).
Run `pre-commit run --all-files`.
If `package.json` defines them, also run:
- `npm run lint`
- `npm run test:ci`
Then run:
- `pyspelling -c .spellcheck.yaml` (requires `aspell` and `aspell-en`; see
  [`.spellcheck.yaml`](../.spellcheck.yaml))
- `linkchecker --no-warnings README.md docs/`
- `git diff --cached | ./scripts/scan-secrets.py` before committing.

USER:
1. Pick one prompt doc under `docs/` (for example, `prompts-codex-cad.md`).
2. Fix outdated instructions, links, or formatting.
3. Run the commands above.

OUTPUT:
A pull request with the improved prompt doc and passing checks.
```
