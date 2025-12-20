// STANDOFF_MODE is passed via -D by openscad_render.sh
// "heatset" → blind hole sized for brass insert
// "printed" → simple through-hole
// "nut"     → through-hole with hex recess
include <./pi_dimensions.scad>;
standoff_mode = is_undef(standoff_mode) ? "heatset" : standoff_mode;
variation = standoff_mode == "printed" ? "through"
          : standoff_mode == "heatset" ? "blind"
          : standoff_mode;

pi_positions = is_undef(pi_positions) ? [[0,0], [1,0], [0,1]] : pi_positions; // layout as [x,y] offsets
board_len = is_undef(board_len) ? 85 : board_len;
board_wid = is_undef(board_wid) ? 56 : board_wid;
hole_spacing = is_undef(hole_spacing) ? pi_hole_spacing : hole_spacing;
hole_spacing_x = hole_spacing[0];
hole_spacing_y = hole_spacing[1];

plate_thickness = is_undef(plate_thickness) ? 2.0 : plate_thickness;
corner_radius   = is_undef(corner_radius) ? 5.0 : corner_radius;  // round base corners to avoid sharp edges
standoff_height = is_undef(standoff_height) ? 6.0 : standoff_height;
standoff_diam = is_undef(standoff_diam) ? 7.0 : standoff_diam;   // widened to keep a ≥0.4 mm flange around the 5.8 mm countersink

insert_od         = is_undef(insert_od) ? 3.5 : insert_od;         // outer Ø for common brass inserts
insert_length     = is_undef(insert_length) ? 4.0 : insert_length;         // full length of the insert
lead_chamfer      = is_undef(lead_chamfer) ? 0.5 : lead_chamfer;         // chamfer depth to guide the insert
insert_pocket_depth = insert_length + lead_chamfer; // pocket allows for chamfer
assert(insert_pocket_depth <= standoff_height,
       "insert_pocket_depth must be ≤ standoff_height");
insert_clearance  = is_undef(insert_clearance) ? 0.2 : insert_clearance;         // designed undersize for interference fit
hole_diam         = insert_od - insert_clearance;
assert(standoff_diam >= insert_od + 2,
       "standoff_diam must be ≥ insert_od + 2");
screw_clearance_diam = 3.2; // through-hole clearance, slightly oversize

countersink_diam = is_undef(countersink_diam) ? 5.8 : countersink_diam; // widened for improved screw head clearance
countersink_depth = is_undef(countersink_depth) ? 1.6 : countersink_depth;

nut_clearance = is_undef(nut_clearance) ? 0.5 : nut_clearance; // extra room for easier nut insertion (was 0.4)
nut_flat = 5.0 + nut_clearance; // across flats for M2.5 nut
nut_thick = is_undef(nut_thick) ? 2.0 : nut_thick;

board_angle = is_undef(board_angle) ? 0 : board_angle;
gap_between_boards = is_undef(gap_between_boards) ? 10 : gap_between_boards;
edge_margin = is_undef(edge_margin) ? 5 : edge_margin;
stack_edge_margin = is_undef(stack_edge_margin) ? 15 : stack_edge_margin;
port_clearance = is_undef(port_clearance) ? 6 : port_clearance;
stack_mount_positions = is_undef(stack_mount_positions) ? undef : stack_mount_positions;

include_stack_mounts = is_undef(include_stack_mounts) ? false : include_stack_mounts;
stack_bolt_d = is_undef(stack_bolt_d) ? 3.4 : stack_bolt_d;
stack_pocket_d = is_undef(stack_pocket_d) ? 9 : stack_pocket_d;
stack_pocket_depth_input = is_undef(stack_pocket_depth_input)
    ? (is_undef(stack_pocket_depth) ? 1.2 : stack_pocket_depth)
    : stack_pocket_depth_input;
stack_pocket_depth = is_undef(stack_pocket_depth)
    ? (include_stack_mounts
        ? min(stack_pocket_depth_input, plate_thickness / 2 - 0.1)
        : stack_pocket_depth_input)
    : stack_pocket_depth;

// Optional 1602 LCD module (80x36 mm PCB)
// Disable by default; set to true to add the LCD mount
include_lcd = is_undef(include_lcd) ? false : include_lcd;
lcd_len = is_undef(lcd_len) ? 80 : lcd_len;
lcd_wid = is_undef(lcd_wid) ? 36 : lcd_wid;
lcd_hole_spacing_x = is_undef(lcd_hole_spacing_x) ? 75 : lcd_hole_spacing_x;
lcd_hole_spacing_y = is_undef(lcd_hole_spacing_y) ? 31 : lcd_hole_spacing_y;

assert(
    !include_stack_mounts || 2 * stack_pocket_depth < plate_thickness,
    "stack_pocket_depth must be < half of plate_thickness so symmetric pockets do not overlap"
);

// ---------- Helper functions ----------
function rot2d(v, ang) = [
    v[0]*cos(ang) - v[1]*sin(ang),
    v[0]*sin(ang) + v[1]*cos(ang)
];

function carrier_dimensions(
    include_stack_mounts = include_stack_mounts,
    stack_edge_margin = stack_edge_margin,
    edge_margin = edge_margin,
    plate_thickness = plate_thickness,
    stack_pocket_depth = stack_pocket_depth,
    hole_spacing = hole_spacing,
    board_angle = board_angle,
    gap_between_boards = gap_between_boards,
    pi_positions = pi_positions,
    board_len = board_len,
    board_wid = board_wid,
    corner_radius = corner_radius,
    port_clearance = port_clearance,
    stack_pocket_d = stack_pocket_d,
    stack_mount_positions_input = stack_mount_positions
) =
    let(
        rotX = abs(board_len * cos(board_angle)) + abs(board_wid * sin(board_angle)),
        rotY = abs(board_len * sin(board_angle)) + abs(board_wid * cos(board_angle)),
        board_spacing_x = rotX + gap_between_boards,
        board_spacing_y = rotY + gap_between_boards,
        max_x = max([for (p = pi_positions) p[0]]),
        max_y = max([for (p = pi_positions) p[1]]),
        carrier_edge_margin = include_stack_mounts ? stack_edge_margin : edge_margin,
        plate_len =
            (max_x + 1) * rotX + max_x * gap_between_boards + 2 * carrier_edge_margin,
        plate_wid =
            (max_y + 1) * rotY + max_y * gap_between_boards + 2 * carrier_edge_margin
            + 2 * port_clearance,
        stack_mount_inset = max(corner_radius + stack_pocket_d / 2 + 2, 12),
        stack_mount_positions_default = [
            [stack_mount_inset, stack_mount_inset],
            [plate_len - stack_mount_inset, stack_mount_inset],
            [stack_mount_inset, plate_wid - stack_mount_inset],
            [plate_len - stack_mount_inset, plate_wid - stack_mount_inset]
        ],
        stack_mount_positions = include_stack_mounts
            ? (is_undef(stack_mount_positions_input)
                ? stack_mount_positions_default
                : stack_mount_positions_input)
            : []
    ) [
        plate_len,
        plate_wid,
        rotX,
        rotY,
        board_spacing_x,
        board_spacing_y,
        stack_mount_positions,
        stack_mount_inset
    ];

function carrier_plate_len(carrier_dims) = carrier_dims[0];
function carrier_plate_wid(carrier_dims) = carrier_dims[1];
function carrier_rotX(carrier_dims) = carrier_dims[2];
function carrier_rotY(carrier_dims) = carrier_dims[3];
function carrier_board_spacing_x(carrier_dims) = carrier_dims[4];
function carrier_board_spacing_y(carrier_dims) = carrier_dims[5];
function carrier_stack_mount_positions(carrier_dims) = carrier_dims[6];
function carrier_stack_mount_inset(carrier_dims) = carrier_dims[7];

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
module base_plate(
    carrier_dims,
    hole_spacing_x,
    hole_spacing_y,
    board_spacing_x,
    board_spacing_y,
    stack_mount_positions
)
{
    plate_len = carrier_plate_len(carrier_dims);
    plate_wid = carrier_plate_wid(carrier_dims);

    difference()
    {
        linear_extrude(height=plate_thickness)
            offset(r=corner_radius)
                square([plate_len - 2*corner_radius,
                        plate_wid - 2*corner_radius]);
        if (variation != "blind") {
            for (pos = pi_positions) {
                pcb_cx = edge_margin + carrier_rotX(carrier_dims)/2 + pos[0]*board_spacing_x;
                pcb_cy = edge_margin + port_clearance + carrier_rotY(carrier_dims)/2 + pos[1]*board_spacing_y;
                for (dx = [-hole_spacing_x/2, hole_spacing_x/2])
                for (dy = [-hole_spacing_y/2, hole_spacing_y/2]) {
                    vec = rot2d([dx,dy], board_angle);
                    translate([pcb_cx+vec[0], pcb_cy+vec[1], -0.01])
                        cylinder(h=countersink_depth + 0.02, r=countersink_diam/2, $fn=32);
                }
            }
            if (include_lcd) {
                lcd_cx = edge_margin + carrier_rotX(carrier_dims)/2 + board_spacing_x;
                lcd_cy = edge_margin + port_clearance + carrier_rotY(carrier_dims)/2 + board_spacing_y;
                for (dx = [-lcd_hole_spacing_x/2, lcd_hole_spacing_x/2])
                for (dy = [-lcd_hole_spacing_y/2, lcd_hole_spacing_y/2])
                    translate([lcd_cx+dx, lcd_cy+dy, -0.01])
                        cylinder(h=countersink_depth + 0.02, r=countersink_diam/2, $fn=32);
            }
        }

        if (include_stack_mounts) {
            for (pos = stack_mount_positions) {
                translate([pos[0], pos[1], -0.01])
                    cylinder(h = plate_thickness + 0.02, r = stack_bolt_d / 2, $fn = 60);

                // Symmetric locating pockets: one on each face so every carrier plate
                // is interchangeable in the stack.
                translate([pos[0], pos[1], plate_thickness - stack_pocket_depth])
                    cylinder(h = stack_pocket_depth + 0.02, r = stack_pocket_d / 2, $fn = 70);
                translate([pos[0], pos[1], -0.01])
                    cylinder(h = stack_pocket_depth + 0.02, r = stack_pocket_d / 2, $fn = 70);
            }
        }
    }
}

// ---------- Assembly ----------
module pi_carrier(
    carrier_dims = undef,
    stack_mount_positions_input = stack_mount_positions
)
{
    carrier_dims_resolved = is_undef(carrier_dims)
        ? carrier_dimensions(
            stack_mount_positions_input = stack_mount_positions_input,
            include_stack_mounts = include_stack_mounts,
            plate_thickness = plate_thickness,
            stack_pocket_depth = stack_pocket_depth,
            edge_margin = edge_margin,
            stack_edge_margin = stack_edge_margin,
            hole_spacing = hole_spacing,
            board_angle = board_angle,
            gap_between_boards = gap_between_boards,
            pi_positions = pi_positions,
            board_len = board_len,
            board_wid = board_wid,
            corner_radius = corner_radius,
            port_clearance = port_clearance,
            stack_pocket_d = stack_pocket_d
        )
        : carrier_dims;

    plate_len = carrier_plate_len(carrier_dims_resolved);
    plate_wid = carrier_plate_wid(carrier_dims_resolved);
    board_spacing_x = carrier_board_spacing_x(carrier_dims_resolved);
    board_spacing_y = carrier_board_spacing_y(carrier_dims_resolved);
    stack_mount_positions = carrier_stack_mount_positions(carrier_dims_resolved);
    stack_mount_inset = carrier_stack_mount_inset(carrier_dims_resolved);
    include_stack_mounts_resolved = len(stack_mount_positions) > 0;

    if (include_stack_mounts_resolved) {
        assert(
            stack_mount_inset * 2 < plate_len && stack_mount_inset * 2 < plate_wid,
            "stack mount inset must keep pockets inside the plate bounds"
        );
        for (pos = stack_mount_positions) {
            assert(
                pos[0] > stack_mount_inset / 2 && pos[0] < plate_len - stack_mount_inset / 2,
                "stack mount X coordinate too close to plate edge"
            );
            assert(
                pos[1] > stack_mount_inset / 2 && pos[1] < plate_wid - stack_mount_inset / 2,
                "stack mount Y coordinate too close to plate edge"
            );
        }
    }

    let(include_stack_mounts = include_stack_mounts_resolved)
        base_plate(
            carrier_dims_resolved,
            hole_spacing_x,
            hole_spacing_y,
            board_spacing_x,
            board_spacing_y,
            stack_mount_positions
        );

    for (pos = pi_positions) {
        pcb_cx = edge_margin + carrier_rotX(carrier_dims)/2 + pos[0]*board_spacing_x;
        pcb_cy = edge_margin + port_clearance + carrier_rotY(carrier_dims)/2 + pos[1]*board_spacing_y;
        for (dx = [-hole_spacing_x/2, hole_spacing_x/2])
        for (dy = [-hole_spacing_y/2, hole_spacing_y/2]) {
            vec = rot2d([dx,dy], board_angle);
            standoff([pcb_cx+vec[0], pcb_cy+vec[1]]);
        }
    }

    if (include_lcd) {
        lcd_cx = edge_margin + carrier_rotX(carrier_dims)/2 + board_spacing_x;
        lcd_cy = edge_margin + port_clearance + carrier_rotY(carrier_dims)/2 + board_spacing_y;
        for (dx = [-lcd_hole_spacing_x/2, lcd_hole_spacing_x/2])
        for (dy = [-lcd_hole_spacing_y/2, lcd_hole_spacing_y/2])
            standoff([lcd_cx+dx, lcd_cy+dy]);
    }
}

if (is_undef(_pi_carrier_auto_render) ? true : _pi_carrier_auto_render) {
    pi_carrier();
}
