---
personas:
  - hardware
---

# Mac mini station

Press-fit saddle cap extension for the Mac mini M4 keyboard station.
The cap slides over the existing top saddle and widens the keyboard tray so a Magic Keyboard
or TKL board will not tip off when bumped.

## Usage

1. Open `hardware/mac-mini-station/scad/mac_mini_station.scad` in OpenSCAD and set
   `keyboard_width_mm` to match your board. Uncomment the full-width preset or keep the
   default tenkeyless value.
2. From the repository root run `hardware/mac-mini-station/scripts/build.sh` to export STL
   files into `hardware/mac-mini-station/stl/`. The script requires
   [OpenSCAD](https://openscad.org/) on your `PATH`.
3. Print the cap upside down without supports.
4. Start with `press_fit_clearance_mm = 0.35` and adjust after a test fit.

## Attribution

Inspired by [Magic Tray – Holder for Apple's Magic Keyboard and Trackpad][magic-tray]
(Thingiverse 4910431) by reddit user **CaptainDarwin**, licensed under CC BY-NC-SA 4.0.
This repository links to the original design and does not redistribute their files.

[magic-tray]: https://archive.org/details/thingiverse-4910431

## License

Code is licensed under the MIT License, see [../LICENSE](../LICENSE).
