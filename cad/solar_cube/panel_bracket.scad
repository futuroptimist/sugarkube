/*
  Parametric L-bracket for mounting solar panels to 2020 extrusion

  Generates three variants:
    standoff_mode="printed" → through-hole for machine screw
    standoff_mode="heatset" → blind hole sized for brass insert
    standoff_mode="nut"     → through-hole with hex recess
  A variable of that name is passed in by the CI render script.
*/

size          = 40;           // leg length (mm)
thickness     = 8;            // plate thickness (mm)
beam_width    = 20;           // width to match 2020 extrusion (mm)
edge_radius   = 3.5;          // default 3.5 mm radius avoids zero-thickness cores
corner_segments = 48;         // higher sphere resolution for smoother edges
hole_offset   = [0,0];        // XY offset of mounting hole from centre (mm)
gusset        = true;         // add triangular support in inner corner
gusset_size   = thickness*1.5; // leg length of gusset triangle (mm)

// insert / screw parameters
insert_od         = 6.3;      // brass insert outer Ø (mm) for typical M5 insert
insert_length     = 6.0;      // insert length (mm)
insert_clearance  = 0.20;     // interference amount (mm)
insert_hole_diam  = insert_od - insert_clearance;
screw_nominal     = 5.0;      // nominal screw size for through-hole (mm)
screw_clearance   = screw_nominal + 0.2; // through-hole Ø with clearance (mm)
chamfer           = 1.0;      // lead-in chamfer (mm)

nut_clearance     = 0.4;      // extra room for easier nut insertion (was 0.2)
nut_flat          = 8.0 + nut_clearance; // across flats for M5 nut (mm)

nut_thick         = 4.0;      // nut thickness (mm)

assert(insert_length < thickness,
       "insert_length must be < thickness to maintain a blind hole");
assert(gusset_size <= size,
       "gusset_size must be ≤ leg length");
assert(insert_length + chamfer <= thickness,
       "insert_length + chamfer must be ≤ thickness");
assert(edge_radius*2 <= min([beam_width, size, thickness]),
       "edge_radius too large for given dimensions");
assert(nut_thick <= thickness,
       "nut_thick must be ≤ thickness");
assert(abs(hole_offset[0]) <= beam_width/2 - screw_clearance/2 - edge_radius,
       "hole_offset[0] exceeds base width");
assert(abs(hole_offset[1]) <= size/2 - screw_clearance/2 - edge_radius,
       "hole_offset[1] exceeds leg length");

// read from CLI (-D standoff_mode="printed"/"heatset"/"nut")
standoff_mode = "heatset";

/* rounded cube helper */
module rounded_cube(dims, r)
{
  if (r <= 0)
    cube(dims);
  else
    minkowski() {
      cube([dims[0]-2*r, dims[1]-2*r, dims[2]-2*r]);
      sphere(r, $fn=corner_segments);
    }
}

module l_bracket()
{
  difference() {
    /* build the two legs */
    union() {
      // base leg lying flat (XY plane)
      rounded_cube([beam_width, size, thickness], edge_radius);

      // vertical leg (XZ plane)
      translate([0, size - thickness, 0])
        rounded_cube([beam_width, thickness, size], edge_radius);

      // optional gusset to reinforce the corner
      if (gusset)
        translate([0, size - thickness, 0])
          rotate([0,90,0])
            linear_extrude(height=beam_width)
              polygon([[0,0],[gusset_size,0],[0,gusset_size]]);
    }

    /* drill hole at centre of base leg for mounting */
    translate([beam_width/2 + hole_offset[0],
              size/2       + hole_offset[1],
              0])
    {
      if (standoff_mode == "printed") {
        // through-hole with lead-in chamfers on both faces
        union() {
          // main clearance hole
          cylinder(h=thickness + 0.2, r=screw_clearance/2, $fn=32);
          // bottom chamfer
          translate([0,0,-0.1])
            cylinder(h=chamfer, r1=screw_clearance/2 + chamfer,
                     r2=screw_clearance/2, $fn=32);
          // top chamfer
          translate([0,0,thickness - chamfer + 0.1])
            cylinder(h=chamfer, r1=screw_clearance/2,
                     r2=screw_clearance/2 + chamfer, $fn=32);
        }
      } else if (standoff_mode == "nut") {
        // through-hole with captive hex recess on underside
        union() {
          cylinder(h=thickness + 0.2, r=screw_clearance/2, $fn=32);
          translate([0,0,-nut_thick + 0.1])
            cylinder(h=nut_thick, r=nut_flat/(2*cos(30)), $fn=6);
          translate([0,0,thickness - chamfer + 0.1])
            cylinder(h=chamfer, r1=screw_clearance/2,
                     r2=screw_clearance/2 + chamfer, $fn=32);
        }
      } else {
        // blind hole for insert
        translate([0,0,thickness - insert_length - 0.1])
          cylinder(h=insert_length + 0.2, r=insert_hole_diam/2, $fn=40);
        // chamfer
        translate([0,0,thickness - insert_length - chamfer])
          cylinder(h=chamfer, r1=insert_hole_diam/2 + chamfer,
                   r2=insert_hole_diam/2, $fn=32);
      }
    }
  }
}

/* shift so bracket base sits on Z=0 */
l_bracket();
