// Basic parametric cube frame
/*
  Parametric 2020-extrusion cube frame

  edge:  overall exterior dimension (mm)
  beam:  extrusion width (typically 20 mm)
*/

edge = 500;        // exterior size of the cube (mm)
beam = 20;         // t-slot extrusion width

module extrusion_frame(edge, beam)
{
  /* Build 12 edge-beams of the cube */

  // vertical edges
  for (x = [0, edge-beam])
  for (y = [0, edge-beam])
    translate([x, y, 0])
      cube([beam, beam, edge]);

  // edges parallel to X-axis (front & back, bottom & top)
  for (y = [0, edge-beam])
  for (z = [0, edge-beam])
    translate([0, y, z])
      cube([edge, beam, beam]);

  // edges parallel to Y-axis (left & right, bottom & top)
  for (x = [0, edge-beam])
  for (z = [0, edge-beam])
    translate([x, 0, z])
      cube([beam, edge, beam]);
}

// shift so that the cube is centered at the origin, matching other models
translate([-edge/2, -edge/2, -edge/2])
  extrusion_frame(edge, beam);
