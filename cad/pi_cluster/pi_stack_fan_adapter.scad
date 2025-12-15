// Fan wall adapter that clamps to stack posts and presents holes matching the
// fan_wall column tabs.
include <./fan_patterns.scad>;
include <./pi_dimensions.scad>;

levels = is_undef(levels) ? 3 : levels;
z_gap_clear = is_undef(z_gap_clear) ? 32 : z_gap_clear;
column_spacing = is_undef(column_spacing) ? pi_hole_spacing : column_spacing;
stack_bolt_d = is_undef(stack_bolt_d) ? 3.4 : stack_bolt_d;
stack_pocket_d = is_undef(stack_pocket_d) ? 8 : stack_pocket_d;
stack_edge_margin = is_undef(stack_edge_margin) ? 15 : stack_edge_margin;
fan_offset_from_stack = is_undef(fan_offset_from_stack) ? 15 : fan_offset_from_stack;
fan_plate_t = is_undef(fan_plate_t) ? 4 : fan_plate_t;
fan_insert_L = is_undef(fan_insert_L) ? 4.0 : fan_insert_L;
column_tab_offset = is_undef(column_tab_offset) ? 6 : column_tab_offset;
column_tab_thickness = is_undef(column_tab_thickness) ? 6 : column_tab_thickness;
adapter_thickness = is_undef(adapter_thickness) ? 6 : adapter_thickness;
bridge_thickness = is_undef(bridge_thickness) ? 4 : bridge_thickness;
clamp_padding = is_undef(clamp_padding) ? 6 : clamp_padding;

// Mirror the pi_carrier defaults to derive sensible stack mount positions when
// consumers do not override them.
pi_positions = [[0,0], [1,0], [0,1]];
board_len = 85;
board_wid = 56;
hole_spacing = pi_hole_spacing;
hole_spacing_x = hole_spacing[0];
hole_spacing_y = hole_spacing[1];
board_angle = 0;
gap_between_boards = 10;
edge_margin = 5;
port_clearance = 6;
rotX = abs(board_len*cos(board_angle)) + abs(board_wid*sin(board_angle));
rotY = abs(board_len*sin(board_angle)) + abs(board_wid*cos(board_angle));
board_spacing_x = rotX + gap_between_boards;
board_spacing_y = rotY + gap_between_boards;
max_x = max([for(p=pi_positions) p[0]]);
max_y = max([for(p=pi_positions) p[1]]);
plate_len = (max_x+1)*rotX + max_x*gap_between_boards + 2*stack_edge_margin;
plate_wid = (max_y+1)*rotY + max_y*gap_between_boards + 2*stack_edge_margin + 2*port_clearance;

function _default_stack_mount_offset(axis_len) =
    axis_len / 2 - max(stack_pocket_d / 2 + 2, stack_edge_margin);

function _default_stack_mount_positions() =
    let(
        offset_x = _default_stack_mount_offset(plate_len),
        offset_y = _default_stack_mount_offset(plate_wid)
    ) [
        [offset_x, offset_y],
        [-offset_x, offset_y],
        [-offset_x, -offset_y],
        [offset_x, -offset_y]
    ];

stack_mount_positions =
    is_undef(stack_mount_positions) ? _default_stack_mount_positions() : stack_mount_positions;

function _fan_side_posts() =
    let(max_x = max([for (p = stack_mount_positions) p[0]]))
        [for (p = stack_mount_positions) if (p[0] == max_x) p];

function _fan_side_sorted() =
    sort(_fan_side_posts(), function (a, b) a[1] < b[1]);

function _mid(a, b) = (a + b) / 2;

function _fan_tab_y() = fan_plate_t + column_tab_thickness / 2;
function _fan_tab_z(level) = column_tab_offset + level * z_gap_clear + (fan_insert_L + 6) / 2;

module _clamp_body(posts, anchor_x, min_y, max_y, height) {
    span_y = max_y - min_y;
    body_width = span_y + clamp_padding * 2;
    start_y = min_y - clamp_padding;
    difference() {
        translate([anchor_x - adapter_thickness / 2, start_y, 0])
            cube([adapter_thickness, body_width, height]);
        for (post = posts)
            translate([post[0], post[1], -0.1])
                cylinder(h = height + 0.2, r = stack_bolt_d / 2, $fn = 40);
    }
}

module _fan_rail(anchor_x, min_y, max_y, height) {
    span_y = max_y - min_y + clamp_padding * 2;
    start_y = min_y - clamp_padding;
    rail_x = anchor_x + fan_offset_from_stack;
    difference() {
        translate([rail_x - adapter_thickness / 2, start_y, 0])
            cube([adapter_thickness, span_y, height]);

        for (level = [0 : levels - 1])
            translate([rail_x, _fan_tab_y(), _fan_tab_z(level)])
                rotate([90, 0, 0])
                    cylinder(h = span_y + 0.4, r = 1.6, $fn = 30);
    }
}

module _bridge(anchor_x, min_y, max_y, height) {
    span_y = max_y - min_y + clamp_padding * 2;
    start_y = min_y - clamp_padding;
    translate([anchor_x - bridge_thickness / 2, start_y, 0])
        cube([fan_offset_from_stack + adapter_thickness, span_y, bridge_thickness]);
}

module pi_stack_fan_adapter() {
    posts = _fan_side_sorted();
    assert(len(posts) == 2, "Expected two posts on the fan side for the adapter");
    min_y = min([for (p = posts) p[1]]);
    max_y = max([for (p = posts) p[1]]);
    anchor_x = posts[0][0];
    height = levels * z_gap_clear + column_tab_offset + fan_insert_L + 3;

    _clamp_body(posts, anchor_x, min_y, max_y, height);
    _fan_rail(anchor_x, min_y, max_y, height);
    _bridge(anchor_x, min_y, max_y, height);
}

pi_stack_fan_adapter();
