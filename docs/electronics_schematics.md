# Electronics Schematics

The `elex` folder collects KiCad and Fritzing designs used throughout the Sugarkube
project. Schematics describe the power distribution ring and related circuits.

## Power Ring KiCad Project

The **power_ring** directory contains a minimal KiCad design used as a starting point
for the Sugarkube power distribution board. The project is based on KiCad's
`custom_pads_test` demo and demonstrates basic footprint libraries and schematic
symbols. It currently exports a small two–layer board that can be iterated on for
real hardware. High‑level requirements live in
[elex/power_ring/specs.md](../elex/power_ring/specs.md).

Included files:

- `power_ring.kicad_pro` – project settings
- `power_ring.kicad_sch` – schematic
- `power_ring.kicad_pcb` – PCB layout
- `power_ring.kicad_sym` and `power_ring_schlib.kicad_sym` – symbol libraries
- `power_ring.pretty/` – footprint library

Design notes embedded in the KiCad title block highlight best practices:

- Place decoupling capacitors near power pins.
- Keep high-current traces short for better performance.
- Label polarity and voltage on connectors to avoid wiring mistakes.
- Verify KiBot exports before fabrication.
- Verify ground-pour clearance around mounting holes.
- Double-check LED orientation during assembly.

Open the project in **KiCad 9** or newer and modify the schematic to suit your power
distribution needs (for example, add screw terminals, fuses and test points). Use
[KiBot](https://github.com/INTI-CMNB/KiBot) with `.kibot/power_ring.yaml` or run the
GitHub workflow to produce Gerber files, a PDF schematic and a BOM in
`build/power_ring/`.
The `scripts/checks.sh` helper now installs KiCad 9 automatically when
you modify `.kicad_*` files (or set `SUGARKUBE_FORCE_KICAD_INSTALL=1`),
pulling the official 9.0 packages on Debian/Ubuntu or the Homebrew cask
elsewhere so exports succeed without manual setup. After installing, it
probes `python`, `python3`, and the common `python3.x` shims so it can
reuse whichever interpreter exposes KiCad's `pcbnew` module—even when
`actions/setup-python` provides a newer Pyenv build that lacks the
package. It also deepens shallow clones and fetches the base branch
during CI so electronics edits are detected even when only the newest
commit is available.

The layout now includes a "SugarKube" copper label for easy identification.

## Fritzing Sketch

Placeholder for wiring diagrams created with Fritzing.
