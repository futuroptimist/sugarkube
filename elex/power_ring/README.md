# Power Ring KiCad Project

The **power_ring** directory contains a minimal KiCad design used as a starting point for the Sugarkube power distribution board.  The project is based on KiCad's `custom_pads_test` demo and demonstrates basic footprint libraries and schematic symbols.  It currently exports a small two–layer board that can be iterated on for real hardware.

Included files:

- `power_ring.kicad_pro` – project settings
- `power_ring.kicad_sch` – schematic
- `power_ring.kicad_pcb` – PCB layout
- `power_ring.kicad_sym` and `power_ring_schlib.kicad_sym` – symbol libraries
- `power_ring.pretty/` – footprint library

Open the project in KiCad 7 or newer and modify the schematic to suit your power distribution needs (e.g., add screw terminals, fuses and test points).  Running `scripts/kicad_export.sh elex/power_ring/power_ring.kicad_pcb` will generate gerber and PDF outputs in `kicad-export/`.
