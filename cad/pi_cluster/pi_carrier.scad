variation = "blind"; // blind, through, nut

pi_positions = [[0,0], [1,0], [0,1]]; // layout as [x,y] offsets
board_len = 85;
board_wid = 56;
hole_spacing_x = 58;
hole_spacing_y = 49;

plate_thickness = 2.0;
standoff_height = 6.0;
standoff_diam = 6.0;

insert_od         = 3.5;         // outer Ø for common brass inserts
insert_length     = 4.0;         // full length of the insert
insert_pocket_depth = insert_length + 0.7; // keeps 0.7 mm extra for chamfer
hole_diam         = insert_od + 0.1;       // slip-fit pilot
lead_chamfer = 0.5;
screw_clearance_diam = 3.0; // through-hole clearance

countersink_diam = 5.0;
countersink_depth = 1.6;

nut_flat = 5.0;   // across flats for M2.5 nut
nut_thick = 2.0;

board_angle = 0;
gap_between_boards = 45;
edge_margin = 5;
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

plate_len = (max_x+1)*rotX + max_x*gap_between_boards + 2*edge_margin;
plate_wid = (max_y+1)*rotY + max_y*gap_between_boards + 2*edge_margin + 2*port_clearance;

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
module base_plate()
{
    difference()
    {
        cube([plate_len, plate_wid, plate_thickness]);
        if (variation != "blind") {
            for (pos = pi_positions) {
                pcb_cx = edge_margin + rotX/2 + pos[0]*board_spacing_x;
                pcb_cy = edge_margin + port_clearance + rotY/2 + pos[1]*board_spacing_y;
                for (dx = [-hole_spacing_x/2, hole_spacing_x/2])
                for (dy = [-hole_spacing_y/2, hole_spacing_y/2]) {
                    vec = rot2d([dx,dy], board_angle);
                    translate([pcb_cx+vec[0], pcb_cy+vec[1], -0.01])
                        cylinder(h=countersink_depth + 0.02, r=countersink_diam/2, $fn=32);
                }
            }
            if (include_lcd) {
                lcd_cx = edge_margin + rotX/2 + board_spacing_x;
                lcd_cy = edge_margin + port_clearance + rotY/2 + board_spacing_y;
                for (dx = [-lcd_hole_spacing_x/2, lcd_hole_spacing_x/2])
                for (dy = [-lcd_hole_spacing_y/2, lcd_hole_spacing_y/2])
                    translate([lcd_cx+dx, lcd_cy+dy, -0.01])
                        cylinder(h=countersink_depth + 0.02, r=countersink_diam/2, $fn=32);
            }
        }
    }
}

// ---------- Assembly ----------
module pi_carrier()
{
    base_plate();

    for (pos = pi_positions) {
        pcb_cx = edge_margin + rotX/2 + pos[0]*board_spacing_x;
        pcb_cy = edge_margin + port_clearance + rotY/2 + pos[1]*board_spacing_y;
        for (dx = [-hole_spacing_x/2, hole_spacing_x/2])
        for (dy = [-hole_spacing_y/2, hole_spacing_y/2]) {
            vec = rot2d([dx,dy], board_angle);
            standoff([pcb_cx+vec[0], pcb_cy+vec[1]]);
        }
    }

    if (include_lcd) {
        lcd_cx = edge_margin + rotX/2 + board_spacing_x;
        lcd_cy = edge_margin + port_clearance + rotY/2 + board_spacing_y;
        for (dx = [-lcd_hole_spacing_x/2, lcd_hole_spacing_x/2])
        for (dy = [-lcd_hole_spacing_y/2, lcd_hole_spacing_y/2])
            standoff([lcd_cx+dx, lcd_cy+dy]);
    }
}

// Preview
if ($preview) {
    pi_carrier();
}

// Auto-render for CLI/F7
if ($preview==false) {
    pi_carrier();
}
