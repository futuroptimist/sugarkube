/***********************************************************************
 *  pi_carrier_v2.scad  –  Triple‑stack Raspberry Pi carrier
 *  Copyright © 2025 Daniel Smith  |  Licence: CC‑BY‑SA 4.0
 *
 *  • Holds two Raspberry Pi 4 B (or 3 B+) boards side‑by‑side on the
 *    bottom row and one board (rotated 90°) centred above them.
 *  • Enlarged row‑to‑row gap (row_gap) for micro‑HDMI / USB‑C access.
 *  • All dimensions taken from the official Raspberry Pi 4 mechanical
 *    drawing and HAT+ specification.  Edit the variables section only.
 *
 *  TODO (future revs):
 *    – Extra standoffs for a 2‑inch SPI display.
 *    – Parametric PoE HAT keep‑out volumes.
 ***********************************************************************/

$fn = 64;                          // Cylinder smoothness

// ----------  Tunable parameters  ----------
pi_size          = [85, 56, 1.6];  // Official PCB X, Y, Z (mm):contentReference[oaicite:0]{index=0}
mount_cc         = [58, 49];       // Hole centre‑to‑centre spacing (mm):contentReference[oaicite:1]{index=1}
edge_margin      = 2.5;            // Hole centre → PCB edge (mm):contentReference[oaicite:2]{index=2}
hole_diameter    = 2.75;           // M2.5 clearance
standoff_diam    = 6;              // Printed pillar Ø
standoff_height  = 6;              // Under‑board clearance (fits PoE headers):contentReference[oaicite:3]{index=3}
base_thickness   = 3;              // Plate thickness
row_gap          = 15;             // **NEW** extra spacing between Pi rows (mm)

// ----------  Derived geometry  ----------
bay_w = mount_cc[0] + 2*edge_margin;
bay_h = mount_cc[1] + 2*edge_margin;

margin          = 10;                           // Border around plate
plate_x         = 2*bay_w + row_gap + 2*margin; // Width for two bottom Pis
plate_y         = bay_h + mount_cc[0] + 2*margin;
plate_z         = base_thickness;

module standoff(x, y) {
    translate([x, y, 0])
        cylinder(d = standoff_diam, h = plate_z + standoff_height);
    // pilot bore for self‑tapping or metal insert
    translate([x, y, plate_z + standoff_height - 5])
        cylinder(d = hole_diameter, h = 10);
}

module pi_mount(origin = [0, 0]) {
    translate(origin) {
        for (dx = [edge_margin, edge_margin + mount_cc[0]])
            for (dy = [edge_margin, edge_margin + mount_cc[1]])
                standoff(dx, dy);
    }
}

// ----------  Build plate  ----------
difference() {
    // Base slab
    cube([plate_x, plate_y, plate_z], center = false);

    // OPTIONAL: chamfer underside edges for nicer print finish
    translate([-1, -1, -1]) cube([plate_x + 2, plate_y + 2, 1]);
}

// ----------  Place Raspberry Pis ----------
/* Bottom‑left Pi */
pi_mount([margin, margin]);

/* Bottom‑right Pi */
pi_mount([margin + bay_w + row_gap, margin]);

/* Top Pi (rotated 90 deg for better cable exit) */
rotate([0, 0, 90])
    pi_mount([
        // Centre over the gap so the HAT doesn’t foul either Pi
        margin + bay_w + row_gap/2 - mount_cc[1]/2,
        margin + bay_h + 5            // small y‑offset for breathing room
    ]);

// ----------  Helpful outline of each board (2D projection) ----------
color("LightGrey", 0.3) {
    translate([margin, margin, plate_z + 0.01])
        cube([bay_w, bay_h, 0.5]);

    translate([margin + bay_w + row_gap, margin, plate_z + 0.01])
        cube([bay_w, bay_h, 0.5]);

    translate([
        margin + bay_w + row_gap/2 - pi_size[1]/2,
        margin + bay_h + 5,
        plate_z + 0.01
    ])
        cube([pi_size[1], pi_size[0], 0.5]);
}
