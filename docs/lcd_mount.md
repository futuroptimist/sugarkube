# Optional LCD Mount

The basic Pi carrier can host a 1602 I²C LCD in the free quadrant.
Its standoffs match the common 80×36 mm module with holes 3 mm from each
edge (75 mm × 31 mm spacing).

LCD support is disabled by default. To add the display set
`include_lcd = true` near the top of `cad/pi_cluster/pi_carrier.scad`
and render the model from the repository root:

```bash
# Render the default heat-set insert variant
bash scripts/openscad_render.sh cad/pi_cluster/pi_carrier.scad

# Render a version with printed threads
STANDOFF_MODE=printed bash scripts/openscad_render.sh cad/pi_cluster/pi_carrier.scad
```

Rotate the LCD or tweak offsets if your board slightly differs. The
extra standoffs avoid the Pi mounting holes so you can add the display
without enlarging the plate.

Valid `STANDOFF_MODE` values are `heatset` (default) and `printed`.
