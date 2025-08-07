/*
  Parametric L-bracket for mounting solar panels to 2020 extrusion

  Generates two variants:
    standoff_mode="printed" → through-hole for machine screw
    standoff_mode="heatset" → blind hole sized for brass insert
  A variable of that name is passed in by the CI render script.
*/

size          = 40;           // leg length (mm)
thickness     = 3;            // plate thickness (mm)
beam_width    = 20;           // width to match 2020 extrusion (mm)
hole_offset   = [0,0];        // XY offset of mounting hole from centre (mm)

// insert / screw parameters
insert_od         = 5.0;      // brass insert outer Ø (mm)
insert_length     = 5.0;
insert_clearance  = 0.15;     // interference amount (mm)
insert_hole_diam  = insert_od - insert_clearance;
screw_clearance   = 5.0;      // through-hole Ø for M5 (mm)
chamfer           = 0.6;      // lead-in chamfer (mm)

// read from CLI (-D standoff_mode="printed"/"heatset")
standoff_mode = "heatset";

module l_bracket()
{
  /* build the two legs */
  union() {
    // base leg lying flat (XY plane)
    cube([beam_width, size, thickness]);

    // vertical leg (XZ plane)
    translate([0, size - thickness, 0])
      cube([beam_width, thickness, size]);
  }

  /* drill hole at centre of base leg for mounting */
  translate([beam_width/2 + hole_offset[0],
            size/2       + hole_offset[1],
            0])
  {
    if (standoff_mode == "printed") {
      // through-hole
      cylinder(h=thickness + 0.2, r=screw_clearance/2, $fn=32);
    } else {
      // blind hole for insert
      translate([0,0,thickness - insert_length - 0.1])
        cylinder(h=insert_length + 0.2, r=insert_hole_diam/2, $fn=40);
      // chamfer
      translate([0,0,thickness - insert_length - chamfer])
        cylinder(h=chamfer, r1=insert_hole_diam/2 + chamfer, r2=insert_hole_diam/2, $fn=32);
    }
  }
}

/* shift so bracket base sits on Z=0 */
l_bracket();
