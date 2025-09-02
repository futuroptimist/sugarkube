# Optional LCD Mount

The basic Pi carrier can host a 1602 I²C LCD in the free quadrant.
Its standoffs match the common 80×36 mm module with holes 3 mm from each
edge (75 mm × 31 mm spacing).

The base plate includes rounded corners set by `corner_radius` (default 5 mm)
to make handling safer. Standoff pillars now use a 6.5 mm diameter to conserve
material while gripping heat‑set inserts firmly.

LCD support is disabled by default. To add the display set
`include_lcd = true` near the top of `cad/pi_cluster/pi_carrier.scad`
and render the model from the repository root:

```bash
# Render the default heat-set insert variant
bash scripts/openscad_render.sh cad/pi_cluster/pi_carrier.scad

# Render a version with printed threads
STANDOFF_MODE=printed bash scripts/openscad_render.sh cad/pi_cluster/pi_carrier.scad

# Render a captive hex recess variant
STANDOFF_MODE=nut bash scripts/openscad_render.sh cad/pi_cluster/pi_carrier.scad
```

## Enable I²C and Connect

After printing the mount, enable the I²C interface and wire the display:

1. On each Pi run `sudo raspi-config nonint do_i2c 0` or use `sudo raspi-config` and enable
   I²C under *Interface Options*.
2. Attach SDA to GPIO2 (pin 3) and SCL to GPIO3 (pin 5). Connect 5 V and ground to power the
   module.
3. Install `i2c-tools` and confirm the screen appears at `0x27` or `0x3F` with `i2cdetect -y 1`.

Rotate the LCD or tweak offsets if your board slightly differs. The extra standoffs avoid the Pi
mounting holes so you can add the display without enlarging the plate.

Valid `STANDOFF_MODE` values are `heatset` (default), `printed`, and `nut`. Values are case-insensitive.
