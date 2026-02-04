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
the docs you will see the term used in both contexts. The physical cube is
designed to be saturated with greenery: ground-level pots and grow bags tuck
between the uprights while hanging planters fill the airspace. Hardy
fruiting plants such as strawberries thrive in this arrangement and literally
embed glucose, fructose, and sucrose—the sugars that inspired the name—into the
structure's living canopy.

## Quick start: 3-node HA k3s cluster

New to sugarkube? Start with the 3-node HA happy path and follow it end-to-end:

- **[Happy path: 3-server HA cluster in two runs](docs/raspi_cluster_setup.md#happy-path-3-server-ha-cluster-in-two-runs)**
  — download the latest Pi image, flash, clone to SSD, bring up dev/staging/prod, and verify the
  cluster.
- **[Raspberry Pi cluster series](docs/index.md#raspberry-pi-cluster-series)** — Part 1/Part 2
  quick-starts plus manual walkthroughs when you want the raw commands.

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
    a consistent entry point across automation helpers. The unified CLI always runs helpers
    from the repository root so relative paths to `scripts/` and docs work even when you
    launch it from nested directories. `tests/test_cli_docs_repo_root.py` guards the docs
    call-out by invoking `monkeypatch.chdir` to enter a temporary folder before
    running both `docs verify` and `docs simplify`. If you prefer, you can also run
    `python -m` commands from the repository root so the package can be imported cleanly;
    from a nested directory, `./scripts/sugarkube ...` (or adding `scripts/` to your `PATH`)
    bootstraps `PYTHONPATH` before forwarding to the CLI. Either way, the CLI executes
    helpers from the repository root so relative paths to scripts and docs remain stable.
  - `install_sugarkube_image.sh` — install the GitHub CLI when missing, download the
    latest release, verify checksums, expand the `.img.xz`, and emit a new
    `.img.sha256`; safe to run via `curl | bash`. Pass `--dry-run` to print the
    download/expansion plan without touching disk. Invoke it from the unified CLI with
    `python -m sugarkube_toolkit pi install [--dry-run] [helper args...]` when you want
    the same behavior without leaving the `sugarkube` entry point.
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
  - `collect_support_bundle.py` — gather Kubernetes, systemd, and Docker diagnostics into timestamped
    archives. Invoke it from the unified CLI with
    `python -m sugarkube_toolkit pi support-bundle [--dry-run] [args...]` when you want the same
    workflow without leaving the `sugarkube` entry point. The CLI `--dry-run` flag prints the
    helper invocation without executing it so you can confirm the host and arguments before running
    the collection (guarded by
    `tests/test_sugarkube_toolkit_cli.py::test_pi_support_bundle_invokes_helper`).
  - `sugarkube_doctor.sh` — chain download dry-runs, flash validation, and linting checks. Invoke it
    from the unified CLI with `python -m sugarkube_toolkit doctor [--dry-run] [-- args...]` to avoid
    memorizing the standalone helper.
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
chain download → verification → flashing with the streaming helper. Prefer go-task? Run
`sudo task pi:flash FLASH_DEVICE=/dev/sdX` to reach the same helper via the Taskfile. Need to forward
additional helper flags? Append `PI_FLASH_ARGS="-- --force"` (or similar) alongside `FLASH_DEVICE`
so both the device and extra arguments are preserved. The recipe variables read `FLASH_DEVICE`
(and optional `DOWNLOAD_ARGS`) from the environment, so prefix the variable as shown. Regression coverage:
`tests/test_taskfile.py::test_taskfile_pi_flash_forwards_flash_device` keeps the go-task wrapper aligned with
these instructions. Both the Makefile, justfile, and Taskfile expose
`download-pi-image`, `install-pi-image`,
`doctor`, and `codespaces-bootstrap`
shortcuts so GitHub
Codespaces users can install prerequisites and flash media without additional shell glue—pick the runner
you prefer (`make codespaces-bootstrap`, `just codespaces-bootstrap`, or `task codespaces-bootstrap`). Go-task
users can also call the hyphenated aliases directly (`task download-pi-image`, `task install-pi-image`),
which forward `DOWNLOAD_ARGS` the same way as the Make and just wrappers. Regression coverage:
`tests/test_codespaces_bootstrap.py` keeps the package lists aligned across each wrapper, and
`tests/test_taskfile.py::test_taskfile_includes_make_style_aliases` ensures the Taskfile mirrors the
documented shortcuts.
`./scripts/sugarkube-latest` remains available when you only need the `.img.xz` artifact with
checksum verification.
Prefer a unified entry point? Run `python -m sugarkube_toolkit pi download --dry-run` from the
repository root to preview the release helper. Once running, the CLI forces the working directory to
the repository root before invoking helpers. Working from a nested directory? Call
`./scripts/sugarkube pi download --dry-run` (or add `scripts/` to your `PATH`) so the wrapper
bootstraps `PYTHONPATH` before forwarding to the CLI. When prerequisites such as the GitHub CLI,
`curl`, or `sha256sum` are missing, the dry-run prints reminders instead of aborting so you can
review the planned commands first. Need the combined installer that downloads and
expands the image? Run

```bash
python -m sugarkube_toolkit pi install --dry-run -- --dir ~/sugarkube/images --image ~/sugarkube/images/sugarkube.img
```

Drop `--dry-run` once you are ready; flags after the standalone `--` flow directly to
`scripts/install_sugarkube_image.sh`.

Reuse the streaming helper via:

```bash
python -m sugarkube_toolkit pi flash --dry-run -- --image ~/sugarkube/images/sugarkube.img --device /dev/sdX
```

Drop `--dry-run` when you're ready to write media.

Prefer a guided experience? Open [docs/flash-helper/](docs/flash-helper/) to paste a workflow run
URL and receive OS-specific download, verification, and flashing steps. The same logic is also
available via `python scripts/workflow_flash_instructions.py --help` for command-line use.

Run `pre-commit run --all-files` before committing.
This triggers `scripts/checks.sh`, which installs required tooling and runs
linters, tests, and documentation checks. If you send patches with `git send-email`,
copy [`hooks/sendemail-validate.sample`](hooks/sendemail-validate.sample) to
`.git/hooks/sendemail-validate` so the email workflow executes the same checks
after applying your series and scans each patch for secrets before sending.
The helper now bootstraps the [`just`](https://github.com/casey/just) binary automatically when it
is missing so the formatting and orchestration recipes never skip; run
`./scripts/install_just.sh` directly when you want to install the tool ahead of the
full check suite.
Running the checks as a non-root user now exports `ALLOW_NON_ROOT=1` and sets
`BATS_CWD`/`BATS_LIB_PATH` to the repository root so Bats fixtures resolve the
same way they do in CI. Overriding `ALLOW_NON_ROOT` with any value other than
`1` causes an immediate failure instead of a confusing permission error.
Regression coverage:
`tests/test_sendemail_validate_hook.py::test_sendemail_hook_runs_repo_checks`
and
`tests/test_sendemail_validate_hook.py::test_sendemail_hook_scans_patches_for_secrets`,
plus `tests/checks_script_test.py::test_exports_test_env_defaults` and
`tests/checks_script_test.py::test_rejects_conflicting_allow_non_root`.

### Integration tests

Set `AVAHI_AVAILABLE=1` to opt into the Avahi-backed mDNS roundtrip test. The
integration suite expects `avahi-publish`, `avahi-browse`, and `avahi-resolve`
to be installed. Run it directly with:

```bash
AVAHI_AVAILABLE=1 bats tests/integration/mdns_roundtrip.bats
```

When you run the broader pytest suite in minimal containers, set
`SUGARKUBE_ALLOW_TOOL_SHIMS=1` to let `tests.conftest.require_tools` create
temporary stand-ins for missing binaries (for example, `ip` and `ping`). Provide
`SUGARKUBE_TOOL_SHIM_DIR=/tmp/shims` to control where the executables are
written. Shims are happy-path stubs that always return exit code ``0`` and the
shim directory is prepended to ``PATH`` while enabled, so prefer using them in
isolated test environments (such as disposable containers or dedicated
virtualenvs) instead of your daily shell. Regression coverage:
`tests/test_require_tools.py::test_require_tools_falls_back_to_shims`.
When installers are unavailable, `require_tools` now reuses the same shim
fallback controlled by `SUGARKUBE_PREINSTALL_TOOL_SHIMS` (defaults to `"1"`) so
per-test checks avoid skipping in constrained environments. Regression coverage:
`tests/test_require_tools.py::test_require_tools_shims_after_install_failure_with_preinstall_enabled`.
When `apt-get` is unavailable, the session-level pre-install hook now shims the
core CLI dependencies ahead of time so integration tests see the expected tools
without waiting for per-test skip handling. Set
`SUGARKUBE_PREINSTALL_TOOL_SHIMS=0` to opt out when you need to exercise real
installations instead of stubs. Regression coverage:
`tests/test_require_tools.py::test_preinstall_test_cli_tools_shims_when_installs_blocked`
and `tests/test_require_tools.py::test_preinstall_test_cli_tools_shim_opt_out`.
Network namespace probes now request the `ip` and `unshare` utilities up front,
falling back to the same tooling installer before retrying with sudo so CI and
local runs converge. Regression coverage:
`tests/test_ensure_root_privileges.py::test_ensure_root_privileges_installs_netns_tools_first`.
Set `SUGARKUBE_NETNS_FALLBACK=xfail` when you want missing network namespace
privileges to be recorded as expected failures instead of skips so the suite
highlights the capability gap without hiding it. Regression coverage:
`tests/test_ensure_root_privileges.py::test_ensure_root_privileges_xfails_when_requested`.

For mDNS end-to-end coverage that depends on network namespaces, set
`SUGARKUBE_ALLOW_NETNS_STUBS=1` when your environment lacks `CAP_NET_ADMIN` or
non-interactive `sudo`. Use `SUGARKUBE_ALLOW_NETNS_STUBS=auto` to attempt real
namespace setup but fall back to stubs on permission errors. The stub yields
deterministic namespace metadata and lets the suite skip only the
multicast-dependent assertions instead of failing when namespace setup is
unavailable. Regression coverage:
`tests/test_netns_stub.py::test_netns_stub_flag_enables_stubbed_environment` and
`tests/test_netns_stub.py::test_netns_stub_auto_mode_falls_back_on_permission_errors`.

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
# or
task docs:verify
```

Both commands shell into the unified CLI via `scripts/sugarkube docs verify`, which in turn runs
`python -m sugarkube_toolkit docs verify`. The CLI executes the same `pyspelling -c .spellcheck.yaml`
and `linkchecker --no-warnings README.md docs/` commands documented throughout the repo. Provide
`DOCS_VERIFY_ARGS="--dry-run"` to preview the commands before they execute. `pyspelling` relies on
`aspell` and the English dictionary (`aspell-en`); install them manually when the helper cannot. The
`scripts/checks.sh` helper attempts to install the dependencies via `apt-get` when missing. When you
want Sugarkube to bootstrap the prerequisites automatically without running the full lint suite, use
the docs
simplification target instead:

```bash
make docs-simplify
# or
just simplify-docs
# or
task docs:simplify
```

Both wrappers call the unified CLI (`sugarkube docs simplify`), which shells into
`scripts/checks.sh --docs-only` to install `pyspelling`, `linkchecker`, and `aspell` before running
the documentation checks. Add `--skip-install` when those dependencies already exist so the helper
reuses the current environment instead of invoking `apt-get` or `pip`. The helper falls back to
`python -m pip` automatically when a standalone `pip` shim is missing so minimal environments still
bootstrap correctly. When you need to run the commands directly:

```bash
sudo apt-get install aspell aspell-en  # Debian/Ubuntu
brew install aspell                    # macOS
pyspelling -c .spellcheck.yaml
linkchecker --no-warnings README.md docs/
```

Prefer the unified CLI? `python -m sugarkube_toolkit docs simplify [--dry-run] [-- args...]`
wraps the same `scripts/checks.sh --docs-only` helper so you can stay inside a single entry point.
Additional arguments after `--` are forwarded directly to the script.
Regression coverage: `tests/checks_script_test.py::test_runs_js_checks_when_package_lock_present`
verifies the helper runs `npm run test:ci` alongside linting and formatting when Node tooling exists,
`tests/checks_script_test.py::test_docs_only_skip_install_uses_existing_tools` exercises the docs-only
`--skip-install` path, and `tests/checks_script_test.py::test_skip_install_avoids_dependency_bootstrap`
covers full runs that reuse preinstalled tooling. `tests/test_docs_verify_wrapper.py::
test_make_docs_verify_runs_cli` exercises the Make target in dry-run mode so these instructions stay
accurate.

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
