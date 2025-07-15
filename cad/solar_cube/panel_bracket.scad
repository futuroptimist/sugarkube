// Simple L bracket for mounting panels to 2020 extrusion
thickness = 3;
size = 40;

module bracket() {
  cube([size, thickness, size]);
}

bracket();
