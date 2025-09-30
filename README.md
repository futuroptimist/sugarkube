# 🍧 sugarkube

[![docs](https://github.com/futuroptimist/sugarkube/actions/workflows/docs.yml/badge.svg?branch=main)](https://github.com/futuroptimist/sugarkube/actions/workflows/docs.yml)
[![spellcheck](https://github.com/futuroptimist/sugarkube/actions/workflows/spellcheck.yml/badge.svg?branch=main)](https://github.com/futuroptimist/sugarkube/actions/workflows/spellcheck.yml)
[![kicad](https://github.com/futuroptimist/sugarkube/actions/workflows/kicad-export.yml/badge.svg?branch=main)](https://github.com/futuroptimist/sugarkube/actions/workflows/kicad-export.yml)
[![stl](https://github.com/futuroptimist/sugarkube/actions/workflows/scad-to-stl.yml/badge.svg?branch=main)](https://github.com/futuroptimist/sugarkube/actions/workflows/scad-to-stl.yml)
[![Coverage](https://codecov.io/gh/futuroptimist/sugarkube/branch/main/graph/badge.svg)](https://codecov.io/gh/futuroptimist/sugarkube)
[![license](https://img.shields.io/github/license/futuroptimist/sugarkube)](LICENSE)
[![Pi image availability](https://img.shields.io/github/v/release/futuroptimist/sugarkube?label=pi%20image)](https://github.com/futuroptimist/sugarkube/releases/latest)
[![hardware boot][hardware-boot-badge]][pi-smoke-test-doc]

An accessible [k3s](https://k3s.io/) platform for Raspberry Pis and SBCs,
integrated with an off-grid solar setup.
The repository also covers the solar cube art installation, which powers aquarium air pumps and
small computers. It doubles as a living trellis—climbing plants weave through the aluminium
extrusions, while shade-loving herbs thrive beneath the panels. Hanging baskets can clip onto the
frame so the installation is surrounded by greenery.

### What's in a name?

"Sugarkube" refers to both the aluminium cube covered in solar panels **and**
the helper scripts that provide "syntactic sugar" for Kubernetes. Throughout
the docs you will see the term used in both contexts.

## Repository layout

- `cad/` — OpenSCAD models of structural parts. See
  [docs/pi_cluster_carrier.md](docs/pi_cluster_carrier.md) for the Pi carrier plate,
  [cad/solar_cube/panel_bracket.scad](cad/solar_cube/panel_bracket.scad) for the solar
  panel bracket with an `edge_radius` parameter (default 4 mm) to round its outer edges,
  and [cad/solar_cube/frame.scad](cad/solar_cube/frame.scad) for a parametric 2020 cube frame.
- `elex/` — KiCad and Fritzing electronics schematics including the `power_ring`
  board (see [elex/power_ring/specs.md](elex/power_ring/specs.md) and
  [docs/electronics_schematics.md](docs/electronics_schematics.md))
- `hardware/` — accessories like the Mac mini keyboard station cap (see
  [docs/mac_mini_station.md](docs/mac_mini_station.md))
- `docs/` — build instructions, safety notes, and learning resources
- [docs/start-here.md](docs/start-here.md) — quick orientation with 15-minute,
  day-one, and advanced reference tracks
- [docs/solar_basics.md](docs/solar_basics.md) — introduction to how solar panels generate
  power
- [docs/electronics_basics.md](docs/electronics_basics.md) — essential circuits and tools
- [docs/power_system_design.md](docs/power_system_design.md) — sizing batteries and
  charge controllers
- [docs/insert_basics.md](docs/insert_basics.md) — guide for heat-set inserts and printed threads
- [docs/network_setup.md](docs/network_setup.md) — connect the Pi cluster to your network
- [docs/lcd_mount.md](docs/lcd_mount.md) — optional 1602 LCD standoff locations
- [docs/pi_headless_provisioning.md](docs/pi_headless_provisioning.md) — headless boot playbook for
  `secrets.env` usage
- [docs/pi_carrier_launch_playbook.md](docs/pi_carrier_launch_playbook.md) — end-to-end launch
  playbook with a 10-minute fast path, persona walkthroughs, and deep reference maps
- [docs/pi_image_quickstart.md](docs/pi_image_quickstart.md) — build, flash, and boot the image
- [docs/pi_image_contributor_guide.md](docs/pi_image_contributor_guide.md) — map automation helpers
  to the docs that describe them
- [docs/pi_carrier_field_guide.md](docs/pi_carrier_field_guide.md) — printable checklist with a PDF
  companion (`docs/pi_carrier_field_guide.pdf`) for the workbench
- [user-data example](docs/templates/cloud-init/user-data.example) — SSH key and WiFi template
- `scripts/` — helper scripts for rendering and exports. See
  [docs/contributor_script_map.md](docs/contributor_script_map.md) for a
  contributor-facing map that ties each helper to the guide that explains it.
  - `download_pi_image.sh` — fetch the latest Pi image via the GitHub CLI; supports `--dry-run`
    metadata checks and reconciles `--dir`/`--output` directories with POSIX `test -ef`
    instead of `realpath` so macOS-friendly symlinks work without extra tooling.
    Invoke it from the unified CLI with
    `python -m sugarkube_toolkit pi download [--dry-run] [helper args...]` when you prefer
    a consistent entry point across automation helpers.
  - `install_sugarkube_image.sh` — install the GitHub CLI when missing, download the
    latest release, verify checksums, expand the `.img.xz`, and emit a new
    `.img.sha256`; safe to run via `curl | bash`
  - `collect_pi_image.sh` — normalize pi-gen output into a single `.img.xz`,
    clean up temporary work directories, use POSIX `test -ef` to compare paths
    without `realpath`, and fall back to `unzip` when `bsdtar` is unavailable
  - `build_pi_image.sh` — build a Raspberry Pi OS image with cloud-init and
    k3s preinstalled; embeds `pi_node_verifier.sh`, clones `token.place` and
    `democratizedspace/dspace` by default, and now ships node exporter,
    cAdvisor, Grafana Agent, and Netdata containers for observability. Customize
    branches with `TOKEN_PLACE_BRANCH` (default `main`) and `DSPACE_BRANCH`
    (default `v3`). Set `CLONE_SUGARKUBE=true` to include this repo and pass
    space-separated Git URLs via `EXTRA_REPOS` to clone additional projects;
    needs a valid `user-data.yaml` and ~10 GB free disk space. Set `DEBUG=1` to
    trace script execution.
  - `flash_pi_media.sh` — stream `.img` or `.img.xz` directly to removable
    media with SHA-256 verification and automatic eject. A PowerShell wrapper
    (`flash_pi_media.ps1`) shells out to the same Python core on Windows.
  - `pi_node_verifier.sh` — check k3s prerequisites; use `--json` for machine output,
    `--full` to print text plus the JSON summary in one run, or `--help` for usage
  - `pi_smoke_test.py` — SSH wrapper that runs the verifier remotely, supports reboot checks,
    and emits JSON summaries for CI harnesses
  - `render_field_guide_pdf.py` — build the Markdown field guide into a single-page PDF without
    extra pip dependencies so releases can refresh the printable checklist automatically
  - `scan-secrets.py` — scan diffs for high-risk patterns using `ripsecrets` when
    available and also run a regex check to catch common tokens
- `outages/` — structured outage records (see
  [docs/outage_catalog.md](docs/outage_catalog.md))
- `tests/` — quick checks for helper scripts and documentation

## Pi image releases

The `pi-image-release` workflow builds a fresh Raspberry Pi OS image on every
push to `main` and once per day. Each run publishes a signed
`sugarkube.img.xz`, its checksum, a provenance manifest, and the full
`pi-gen` build log. Release notes summarize stage timings and link directly to
the manifest so you can verify the build inputs and commit hashes before
 flashing. Run `./scripts/install_sugarkube_image.sh` (or fetch the same helper
 via `curl -fsSL https://raw.githubusercontent.com/futuroptimist/sugarkube/main/scripts/install_sugarkube_image.sh | bash`) to
 download, verify, and expand the latest release. When you prefer a task runner,
use either `sudo make flash-pi FLASH_DEVICE=/dev/sdX` or `sudo FLASH_DEVICE=/dev/sdX just flash-pi` to
chain download → verification → flashing with the streaming helper. The recipe variables read
`FLASH_DEVICE` (and optional `DOWNLOAD_ARGS`) from the environment, so prefix the variable as shown. Both the
Makefile and justfile expose `download-pi-image`, `install-pi-image`, `doctor`, and `codespaces-bootstrap`
shortcuts so GitHub
Codespaces users can install prerequisites and flash media without additional shell glue.
`./scripts/sugarkube-latest` remains available when you only need the `.img.xz` artifact with
checksum verification.

Prefer a guided experience? Open [docs/flash-helper/](docs/flash-helper/) to paste a workflow run
URL and receive OS-specific download, verification, and flashing steps. The same logic is also
available via `python scripts/workflow_flash_instructions.py --help` for command-line use.

Run `pre-commit run --all-files` before committing.
This triggers `scripts/checks.sh`, which installs required tooling and runs
linters, tests, and documentation checks.

[hardware-boot-badge]: https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/futuroptimist/sugarkube/main/docs/status/hardware-boot.json
[pi-smoke-test-doc]: docs/pi_smoke_test.md

## Getting Started

```bash
git clone https://github.com/futuroptimist/sugarkube.git
# or with SSH:
# git clone git@github.com:futuroptimist/sugarkube.git
cd sugarkube
pip install pre-commit pyspelling linkchecker
pre-commit install
pre-commit run --all-files
```

If you update documentation, install `aspell` and verify spelling and links.
Prefer the combined helper when editing Markdown so spellcheck and link checks stay aligned with the
automation mapping surfaced in [docs/pi_image_contributor_guide.md](docs/pi_image_contributor_guide.md):

```bash
make docs-verify
# or
just docs-verify
```

Both commands call `scripts/docs_verify.sh`, which prints a deprecation notice before handing off to
`python -m sugarkube_toolkit docs verify`. The CLI runs the same `pyspelling -c .spellcheck.yaml`
and `linkchecker --no-warnings README.md docs/` commands documented throughout the repo.
`pyspelling` relies on `aspell` and the English dictionary (`aspell-en`); install them manually when
the helper cannot. The `scripts/checks.sh` helper attempts to install the dependencies via
`apt-get` when missing. When you want Sugarkube to bootstrap the prerequisites automatically without
running the full lint suite, use the docs
simplification target instead:

```bash
make docs-simplify
# or
just simplify-docs
```

Both wrappers call `scripts/checks.sh --docs-only`, which installs `pyspelling`, `linkchecker`, and
`aspell` when possible before running the documentation checks. The helper falls back to
`python -m pip` automatically when a standalone `pip` shim is missing so minimal
environments still bootstrap correctly. When you need to run the commands directly:

```bash
sudo apt-get install aspell aspell-en  # Debian/Ubuntu
brew install aspell                    # macOS
pyspelling -c .spellcheck.yaml
linkchecker --no-warnings README.md docs/
```

The `--no-warnings` flag prevents linkchecker from returning a non-zero exit code on benign Markdown
parsing warnings.

Scan staged changes for secrets before committing:

```bash
git diff --cached | ./scripts/scan-secrets.py
```

If the repository includes a `package.json` but `npm` or `package-lock.json`
are missing, `scripts/checks.sh` will warn and skip JavaScript-specific
checks.

STL files are produced automatically by CI for each OpenSCAD model and can be
downloaded from the workflow run. Provide a single `.scad` file path to render a
variant locally. The script accepts only one argument and prints a usage
message if others are supplied:

```bash
bash scripts/openscad_render.sh cad/pi_cluster/pi5_triple_carrier_rot45.scad
STANDOFF_MODE=printed bash scripts/openscad_render.sh cad/pi_cluster/pi5_triple_carrier_rot45.scad
STANDOFF_MODE=nut bash scripts/openscad_render.sh cad/pi_cluster/pi5_triple_carrier_rot45.scad
```

By default the script uses the model's `standoff_mode` value (`heatset`).
Set `STANDOFF_MODE=printed` to generate 3D-printed threads or `STANDOFF_MODE=nut` for a
captive hex recess. Values are case-insensitive and ignore surrounding whitespace;
`heatset`, `printed`, and `nut` are accepted. Supplying only whitespace uses the model's
default `standoff_mode`.

The helper script validates that the provided `.scad` file exists and that
OpenSCAD is available in `PATH`, printing a helpful error if either check fails.
It separates options from the file path with `--` and handles filenames
that begin with a dash, whether absolute or relative.
The `.scad` extension is matched case-insensitively without Bash 4 features, so
`MODEL.SCAD` works even on macOS default Bash 3.2.

## Community

See [CONTRIBUTING.md](CONTRIBUTING.md) for ways to help.
Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

See [AGENTS.md](AGENTS.md) for included LLM assistants.
See [llms.txt](llms.txt) for an overview suitable for language models.
