// STANDOFF_MODE is passed via -D by openscad_render.sh
// "heatset" → blind hole sized for brass insert
// "printed" → simple through-hole
// "nut"     → through-hole with hex recess
include <./pi_dimensions.scad>;
standoff_mode = is_undef(standoff_mode) ? "heatset" : standoff_mode;
variation = standoff_mode == "printed" ? "through"
          : standoff_mode == "heatset" ? "blind"
          : standoff_mode;
include_stack_mounts =
    is_undef(include_stack_mounts) ? false : include_stack_mounts;
stack_bolt_d = is_undef(stack_bolt_d) ? 3.4 : stack_bolt_d;
stack_pocket_d = is_undef(stack_pocket_d) ? 8 : stack_pocket_d;
stack_pocket_depth = is_undef(stack_pocket_depth) ? 1.6 : stack_pocket_depth;
stack_edge_margin = is_undef(stack_edge_margin) ? 15 : stack_edge_margin;

pi_positions = [[0,0], [1,0], [0,1]]; // layout as [x,y] offsets
board_len = 85;
board_wid = 56;
hole_spacing = is_undef(hole_spacing) ? pi_hole_spacing : hole_spacing;
hole_spacing_x = hole_spacing[0];
hole_spacing_y = hole_spacing[1];

plate_thickness = 2.0;
corner_radius   = 5.0;  // round base corners to avoid sharp edges
standoff_height = 6.0;
standoff_diam = 7.0;   // widened to keep a ≥0.4 mm flange around the 5.8 mm countersink

insert_od         = 3.5;         // outer Ø for common brass inserts
insert_length     = 4.0;         // full length of the insert
lead_chamfer      = 0.5;         // chamfer depth to guide the insert
insert_pocket_depth = insert_length + lead_chamfer; // pocket allows for chamfer
assert(insert_pocket_depth <= standoff_height,
       "insert_pocket_depth must be ≤ standoff_height");
insert_clearance  = 0.2;         // designed undersize for interference fit
hole_diam         = insert_od - insert_clearance;
assert(standoff_diam >= insert_od + 2,
       "standoff_diam must be ≥ insert_od + 2");
screw_clearance_diam = 3.2; // through-hole clearance, slightly oversize

countersink_diam = 5.8; // widened for improved screw head clearance
countersink_depth = 1.6;

nut_clearance = 0.5; // extra room for easier nut insertion (was 0.4)
nut_flat = 5.0 + nut_clearance; // across flats for M2.5 nut
nut_thick = 2.0;

board_angle = 0;
gap_between_boards = 10;
edge_margin = is_undef(edge_margin) ? 5 : edge_margin;
port_clearance = 6;

// Optional 1602 LCD module (80x36 mm PCB)
// Disable by default; set to true to add the LCD mount
include_lcd = false;
lcd_len = 80;
lcd_wid = 36;
lcd_hole_spacing_x = 75;
lcd_hole_spacing_y = 31;

// ---------- Derived dimensions ----------
rotX = abs(board_len*cos(board_angle)) + abs(board_wid*sin(board_angle));
rotY = abs(board_len*sin(board_angle)) + abs(board_wid*cos(board_angle));

board_spacing_x = rotX + gap_between_boards;
board_spacing_y = rotY + gap_between_boards;

max_x = max([for(p=pi_positions) p[0]]);
max_y = max([for(p=pi_positions) p[1]]);

_edge_margin = include_stack_mounts ? stack_edge_margin : edge_margin;
plate_len = (max_x+1)*rotX + max_x*gap_between_boards + 2*_edge_margin;
plate_wid = (max_y+1)*rotY + max_y*gap_between_boards + 2*_edge_margin + 2*port_clearance;

function _default_stack_mount_positions() = [
    [ plate_len / 2 - stack_edge_margin,  plate_wid / 2 - stack_edge_margin],
    [-plate_len / 2 + stack_edge_margin,  plate_wid / 2 - stack_edge_margin],
    [ plate_len / 2 - stack_edge_margin, -plate_wid / 2 + stack_edge_margin],
    [-plate_len / 2 + stack_edge_margin, -plate_wid / 2 + stack_edge_margin]
];

stack_mount_positions = is_undef(stack_mount_positions)
    ? _default_stack_mount_positions()
    : stack_mount_positions;

// ---------- Helper functions ----------
function rot2d(v, ang) = [
    v[0]*cos(ang) - v[1]*sin(ang),
    v[0]*sin(ang) + v[1]*cos(ang)
];

// ---------- Standoff with variant features ----------
module standoff(pos=[0,0])
{
    translate([pos[0], pos[1], plate_thickness])
    difference()
    {
        cylinder(h=standoff_height, r=standoff_diam/2, $fn=60);

        if (variation == "blind") {
            translate([0,0, standoff_height - insert_pocket_depth])
                cylinder(h=insert_pocket_depth, r=hole_diam/2, $fn=32);
            translate([0,0, standoff_height - insert_pocket_depth])
                cylinder(h=lead_chamfer,
                         r1=hole_diam/2 + lead_chamfer,
                         r2=hole_diam/2, $fn=32);
        }
        else if (variation == "through") {
            translate([0,0,-0.01])
                cylinder(h=standoff_height + 0.02, r=screw_clearance_diam/2, $fn=30);
        }
        else if (variation == "nut") {
            translate([0,0,-0.01])
                cylinder(h=standoff_height + 0.02, r=screw_clearance_diam/2, $fn=30);
            translate([0,0,-nut_thick])
                cylinder(h=nut_thick, r=nut_flat/(2*cos(30)), $fn=6);
        }
    }
}

// ---------- Base plate ----------
module _stack_mount(pos=[0,0])
{
    translate([pos[0], pos[1], 0])
        cylinder(h = stack_pocket_depth, r = stack_pocket_d / 2, $fn = 80);
    translate([pos[0], pos[1], -0.1])
        cylinder(h = plate_thickness + 0.2, r = stack_bolt_d / 2, $fn = 60);
}

module base_plate()
{
    difference()
    {
        linear_extrude(height=plate_thickness)
            offset(r=corner_radius)
                square([plate_len - 2*corner_radius,
                        plate_wid - 2*corner_radius]);
        if (variation != "blind") {
            for (pos = pi_positions) {
                pcb_cx = _edge_margin + rotX/2 + pos[0]*board_spacing_x;
                pcb_cy = _edge_margin + port_clearance + rotY/2 + pos[1]*board_spacing_y;
                for (dx = [-hole_spacing_x/2, hole_spacing_x/2])
                for (dy = [-hole_spacing_y/2, hole_spacing_y/2]) {
                    vec = rot2d([dx,dy], board_angle);
                    translate([pcb_cx+vec[0], pcb_cy+vec[1], -0.01])
                        cylinder(h=countersink_depth + 0.02, r=countersink_diam/2, $fn=32);
                }
            }
            if (include_lcd) {
                lcd_cx = _edge_margin + rotX/2 + board_spacing_x;
                lcd_cy = _edge_margin + port_clearance + rotY/2 + board_spacing_y;
                for (dx = [-lcd_hole_spacing_x/2, lcd_hole_spacing_x/2])
                for (dy = [-lcd_hole_spacing_y/2, lcd_hole_spacing_y/2])
                    translate([lcd_cx+dx, lcd_cy+dy, -0.01])
                        cylinder(h=countersink_depth + 0.02, r=countersink_diam/2, $fn=32);
            }
        }

        if (include_stack_mounts) {
            for (mount_pos = stack_mount_positions) {
                translate([mount_pos[0] + plate_len/2,
                           mount_pos[1] + plate_wid/2,
                           0])
                    _stack_mount();
            }
        }
    }
}

// ---------- Assembly ----------
module pi_carrier()
{
    base_plate();

    for (pos = pi_positions) {
        pcb_cx = _edge_margin + rotX/2 + pos[0]*board_spacing_x;
        pcb_cy = _edge_margin + port_clearance + rotY/2 + pos[1]*board_spacing_y;
        for (dx = [-hole_spacing_x/2, hole_spacing_x/2])
        for (dy = [-hole_spacing_y/2, hole_spacing_y/2]) {
            vec = rot2d([dx,dy], board_angle);
            standoff([pcb_cx+vec[0], pcb_cy+vec[1]]);
        }
    }

    if (include_lcd) {
        lcd_cx = _edge_margin + rotX/2 + board_spacing_x;
        lcd_cy = _edge_margin + port_clearance + rotY/2 + board_spacing_y;
        for (dx = [-lcd_hole_spacing_x/2, lcd_hole_spacing_x/2])
        for (dy = [-lcd_hole_spacing_y/2, lcd_hole_spacing_y/2])
            standoff([lcd_cx+dx, lcd_cy+dy]);
    }
}

if (is_undef(_pi_carrier_auto_render) ? true : _pi_carrier_auto_render) {
    pi_carrier();
}
