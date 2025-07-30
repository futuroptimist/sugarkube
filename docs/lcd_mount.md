# Optional LCD Mount

The basic Pi carrier can host a 1602 I²C LCD in the free quadrant.
Standoffs match the common 80×36 mm module with holes 3 mm from each
edge (75 mm × 31 mm hole spacing).

LCD support is disabled by default. Enable the display by setting
`include_lcd = true` near the top of `cad/pi_cluster/pi_carrier.scad`
then render the model:

```bash
openscad cad/pi_cluster/pi_carrier.scad
```

Rotate the LCD or tweak offsets if your board slightly differs. The
extra standoffs keep clear of the Pi mounting holes so you can add the
display without enlarging the plate.
