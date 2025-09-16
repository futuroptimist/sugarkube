/**********************************************************************
 * pi5_triple_carrier_v3_flat.scad  ·  v2.0 (heat-set insert support)
 * Triple-Raspberry-Pi-5 carrier, 45° rotated PCB orientation
 *********************************************************************/

/* ---------- USER-EDITABLE PARAMETERS ---------- */
/* layout of Pi boards as [x,y] offsets forming a 2x2 grid with one corner empty */
pi_positions = [[0,0], [1,0], [0,1]];
num_pis     = len(pi_positions); // how many Pi-5s
board_len          = 85;         // X-size of Pi-5 PCB  (mm)
board_wid          = 56;         // Y-size of Pi-5 PCB  (mm)
hole_spacing_x     = 58;         // long-direction hole spacing (mm)
hole_spacing_y     = 49;         // short-direction hole spacing (mm)
plate_thickness    = 4;          // base-plate thickness (mm)
corner_radius     = 5;          // round base corners to avoid sharp edges

gap_between_boards = 10;         // service gap between rotated PCBs (mm)

// tighter outer margins
edge_margin        = 5;          // was 10 mm
// still enough room for plugs but less overshoot
port_clearance     = 6;          // was 8 mm

board_angle        = 45;          // rotation of each PCB (deg)

/* ---------- FASTENER CHECK ---------- */
screw_length     = 22;   // length of the M2.5 pan-head screw in millimetres
spacer_length    = 11;   // nominal brass spacer height

/* Ensure the selected screw is long enough:
     screw ≥ spacer + Pi-PCB (1.6 mm) + minimum engagement (3 mm)
*/
required_len = spacer_length + 1.6 + 3;
assert(screw_length >= required_len,
       str("Screw too short: need at least ", required_len, " mm"));

/* ---------- STANDOFF & INSERT OPTIONS ---------- */
standoff_height = 6;             // pillar height under PCB (mm)
standoff_diam   = 6.5;           // increased for added strength (mm)

/* Choose one of:
 *  "printed"   → generate printable ISO metric threads (M2.5)
 *  "heatset"   → leave a blind hole sized for a brass M2 insert
 *  "nut"       → through-hole with captive hex recess
 */
standoff_mode   = "heatset";

/* ---- heat-set insert geometry (M2 short, 3 mm OD, 3 mm long) ---- */
insert_od         = 3.00;        // outer diameter of the insert (mm)
insert_length     = 3.00;        // nominal length (mm)
insert_clearance  = 0.20;        // designed undersize for interference fit (mm)
insert_hole_diam  = insert_od - insert_clearance; // about 2.8 mm
insert_chamfer    = 0.5;         // chamfer to guide the soldering tip

/* ---- screw / printed thread geometry (unchanged) ---- */
screw_major     = 2.50;   // M2.5
screw_pitch     = 0.45;   // ISO coarse
thread_facets   = 32;     // helix resolution
screw_clearance = 3.2;    // through-hole clearance, slightly oversize
nut_clearance   = 0.4;    // extra room for easier nut insertion (was 0.3)
nut_flat        = 5.0 + nut_clearance; // across flats for M2.5 nut
nut_thick       = 2.0;    // nut thickness

/* ---------- DERIVED DIMENSIONS ---------- */
/* footprint of a single PCB after rotation */
rotX = abs(board_len*cos(board_angle)) + abs(board_wid*sin(board_angle));
rotY = abs(board_len*sin(board_angle)) + abs(board_wid*cos(board_angle));

board_spacing_x = rotX + gap_between_boards;
board_spacing_y = rotY + gap_between_boards;

max_x = max([for(p=pi_positions) p[0]]);
max_y = max([for(p=pi_positions) p[1]]);

plate_len = (max_x+1)*rotX + max_x*gap_between_boards + 2*edge_margin;
plate_wid = (max_y+1)*rotY + max_y*gap_between_boards + 2*edge_margin + 2*port_clearance;

/* ---------- HELPERS ---------- */
function rot2d(v, ang) = [
    v[0]*cos(ang) - v[1]*sin(ang),
    v[0]*sin(ang) + v[1]*cos(ang)
];

/* ---------- THREAD GENERATOR (printed threads only) ---------- */
module metric_thread(dia=screw_major, pitch=screw_pitch,
                     length=6, internal=false, fn=thread_facets)
{
    turns = length / pitch;
    rotate_extrude($fn=fn*2, convexity=4)
        translate([dia/2,0,0])
            linear_extrude(height=length, twist=-360*turns)
                offset(r=internal ? -0.12 : 0)
                    square([0.54*pitch,0.001]);
}

/* ---------- STANDOFF WITH OPTIONAL INSERT BORE ---------- */
module standoff(pos=[0,0])
{
    translate([pos[0],pos[1],plate_thickness])
    difference()
    {
        /* outer pillar */
        cylinder(h=standoff_height, r=standoff_diam/2, $fn=60);

        /* inner features */
        if (standoff_mode == "printed") {
            translate([0,0,-0.01])
                metric_thread(length=standoff_height+0.02, internal=true);
        }
        else if (standoff_mode == "heatset") {
            /* blind hole sized for M2 brass insert */
            translate([0,0,standoff_height - insert_length - 0.1])
                cylinder(h=insert_length + 0.2,
                         r=insert_hole_diam/2, $fn=40);
            /* guide chamfer */
            translate([0,0,standoff_height - insert_length - insert_chamfer])
                cylinder(h=insert_chamfer,
                         r1=insert_hole_diam/2 + insert_chamfer,
                         r2=insert_hole_diam/2, $fn=32);
        }
        else if (standoff_mode == "nut") {
            /* through-hole with captive hex recess */
            translate([0,0,-0.01])
                cylinder(h=standoff_height + 0.02, r=screw_clearance/2, $fn=32);
            translate([0,0,standoff_height - nut_thick - 0.01])
                cylinder(h=nut_thick + 0.02,
                         r=nut_flat/(2*cos(30)), $fn=6);
        }
    }
}

/* ---------- PLATE BASE ---------- */
difference()
{
    linear_extrude(height=plate_thickness)
        offset(r=corner_radius)
            square([plate_len - 2*corner_radius,
                    plate_wid - 2*corner_radius]);

    /* screw-head relief */
    head_r = 2.5;  // counterbore radius (5 mm diameter)
    head_h = 1.8;  // deeper counterbore fully seats M2.5 pan-head screws

    for (pos = pi_positions) {
        pcb_cx = edge_margin + rotX/2 + pos[0]*board_spacing_x;
        pcb_cy = edge_margin + port_clearance + rotY/2 + pos[1]*board_spacing_y;

        for (dx = [-hole_spacing_x/2, hole_spacing_x/2])
        for (dy = [-hole_spacing_y/2, hole_spacing_y/2]) {
            vec = rot2d([dx,dy], board_angle);
            translate([pcb_cx+vec[0], pcb_cy+vec[1], -0.01])
                cylinder(h=head_h, r=head_r, $fn=40);
        }
    }
}

/* ---------- STANDOFF ARRAY ---------- */
for (pos = pi_positions) {
    pcb_cx = edge_margin + rotX/2 + pos[0]*board_spacing_x;
    pcb_cy = edge_margin + port_clearance + rotY/2 + pos[1]*board_spacing_y;

    for (dx = [-hole_spacing_x/2, hole_spacing_x/2])
    for (dy = [-hole_spacing_y/2, hole_spacing_y/2]) {
        vec = rot2d([dx,dy], board_angle);
        standoff([pcb_cx+vec[0], pcb_cy+vec[1]]);
    }
}
