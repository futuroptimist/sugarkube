// Basic parametric cube frame
/*
  Parametric 2020-extrusion cube frame

  edge_len: overall exterior dimension (mm)
  beam:     extrusion width (typically 20 mm)
  centered: shift frame to origin when true
*/
edge_len = 500;    // exterior size of the cube (mm)
beam = 20;         // t-slot extrusion width
centered = true;   // translate to origin

assert(edge_len > beam,
       "edge_len must be greater than the extrusion beam width");

module extrusion_frame(edge_len, beam)
{
  /* Build 12 edge-beams of the cube */

  // vertical edges
  for (x = [0, edge_len-beam])
  for (y = [0, edge_len-beam])
    translate([x, y, 0])
      cube([beam, beam, edge_len]);

  // edges parallel to X-axis (front & back, bottom & top)
  for (y = [0, edge_len-beam])
  for (z = [0, edge_len-beam])
    translate([0, y, z])
      cube([edge_len, beam, beam]);

  // edges parallel to Y-axis (left & right, bottom & top)
  for (x = [0, edge_len-beam])
  for (z = [0, edge_len-beam])
    translate([x, 0, z])
      cube([beam, edge_len, beam]);
}

// optionally centre the cube at the origin
if (centered)
  translate([-edge_len/2, -edge_len/2, -edge_len/2])
    extrusion_frame(edge_len, beam);
else
  extrusion_frame(edge_len, beam);
