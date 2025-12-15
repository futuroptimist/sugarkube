// STL artifacts + build docs:
// - Spec: docs/pi_cluster_stack.md
// - CI workflow: https://github.com/futuroptimist/sugarkube/actions/workflows/scad-to-stl.yml
// - Artifact: stl-${GITHUB_SHA} (contains modular stack parts)
_pi_carrier_auto_render = false;
include <./pi_dimensions.scad>;
include <./pi_carrier.scad>;
use <./pi_stack_post.scad>;
use <./pi_stack_fan_adapter.scad>;
use <./fan_wall.scad>;

levels = is_undef(levels) ? 3 : levels;
z_gap_clear = is_undef(z_gap_clear) ? 32 : z_gap_clear;
fan_size = is_undef(fan_size) ? 120 : fan_size;
fan_plate_t = is_undef(fan_plate_t) ? 4 : fan_plate_t;
fan_insert_od = is_undef(fan_insert_od) ? 5.0 : fan_insert_od;
fan_insert_L = is_undef(fan_insert_L) ? 4.0 : fan_insert_L;
fan_offset_from_stack = is_undef(fan_offset_from_stack) ? 15 : fan_offset_from_stack;
column_spacing = is_undef(column_spacing) ? pi_hole_spacing : column_spacing;
export_part = is_undef(export_part) ? "assembly" : export_part;
stack_standoff_mode = is_undef(standoff_mode) ? "heatset" : standoff_mode;
stack_edge_margin = is_undef(stack_edge_margin) ? 15 : stack_edge_margin;
stack_bolt_d = is_undef(stack_bolt_d) ? 3.4 : stack_bolt_d;
stack_pocket_d = is_undef(stack_pocket_d) ? 8 : stack_pocket_d;
stack_pocket_depth = is_undef(stack_pocket_depth) ? 0.6 : stack_pocket_depth;
stack_mount_positions = stack_mount_positions;
alignment_guard_enabled =
    is_undef(alignment_guard_enabled) ? true : alignment_guard_enabled;
column_alignment_tolerance =
    is_undef(column_alignment_tolerance) ? 0.2 : column_alignment_tolerance;
expected_column_spacing = pi_hole_spacing;
emit_dimension_report =
    is_undef(emit_dimension_report) ? false : emit_dimension_report;

pi_positions = [[0,0], [1,0], [0,1]];
board_len = 85;
board_wid = 56;
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

stack_plate_len = (max_x+1)*rotX + max_x*gap_between_boards + 2*stack_edge_margin;
stack_plate_wid = (max_y+1)*rotY + max_y*gap_between_boards + 2*stack_edge_margin + 2*port_clearance;

function _default_stack_mount_offset(axis_len) =
    axis_len / 2 - max(stack_pocket_d / 2 + 2, stack_edge_margin);

function _default_stack_mount_positions() =
    let(
        offset_x = _default_stack_mount_offset(stack_plate_len),
        offset_y = _default_stack_mount_offset(stack_plate_wid)
    ) [
        [offset_x, offset_y],
        [-offset_x, offset_y],
        [-offset_x, -offset_y],
        [offset_x, -offset_y]
    ];

function _stack_mount_positions() =
    is_undef(stack_mount_positions) ? _default_stack_mount_positions() : stack_mount_positions;

module _carrier(level) {
    translate([-stack_plate_len / 2, -stack_plate_wid / 2, level * z_gap_clear])
        let(
            include_stack_mounts = true,
            stack_mount_positions = _stack_mount_positions(),
            stack_edge_margin = stack_edge_margin,
            stack_bolt_d = stack_bolt_d,
            stack_pocket_d = stack_pocket_d,
            stack_pocket_depth = stack_pocket_depth,
            standoff_mode = stack_standoff_mode
        ) pi_carrier();
}

module _posts() {
    positions = _stack_mount_positions();
    for (level = [0 : levels - 2])
        for (pos = positions)
            translate([pos[0], pos[1], level * z_gap_clear + plate_thickness])
                pi_stack_post(
                    stack_bolt_d = stack_bolt_d,
                    stack_pocket_d = stack_pocket_d,
                    stack_pocket_depth = stack_pocket_depth,
                    post_height = z_gap_clear - plate_thickness
                );
}

module _fan_wall_adapter() {
    translate([0, 0, 0])
        pi_stack_fan_adapter(
            levels = levels,
            z_gap_clear = z_gap_clear,
            column_spacing = column_spacing,
            stack_bolt_d = stack_bolt_d,
            stack_pocket_d = stack_pocket_d,
            stack_edge_margin = stack_edge_margin,
            fan_offset_from_stack = fan_offset_from_stack,
            fan_plate_t = fan_plate_t,
            fan_insert_L = fan_insert_L,
            stack_mount_positions = _stack_mount_positions()
        );
}

module _fan_wall() {
    translate([column_spacing[0] / 2 + fan_offset_from_stack, 0, 0])
        fan_wall(
            fan_size = fan_size,
            fan_plate_t = fan_plate_t,
            fan_insert_od = fan_insert_od,
            fan_insert_L = fan_insert_L,
            levels = levels,
            z_gap_clear = z_gap_clear,
            column_spacing = column_spacing,
            emit_dimension_report = emit_dimension_report
        );
}

module pi_carrier_stack_assembly() {
    for (level = [0 : levels - 1])
        _carrier(level);
    _posts();
    _fan_wall_adapter();
    _fan_wall();
}

if (emit_dimension_report) {
    stack_height = levels * z_gap_clear;
    echo(
        "pi_carrier_stack",
        levels = levels,
        fan_size = fan_size,
        column_spacing = column_spacing,
        stack_height = stack_height,
        export_part = export_part
    );
}

if (export_part == "carrier_level") {
    _carrier(0);
} else if (export_part == "post") {
    pi_stack_post(
        stack_bolt_d = stack_bolt_d,
        stack_pocket_d = stack_pocket_d,
        stack_pocket_depth = stack_pocket_depth,
        post_height = z_gap_clear - plate_thickness
    );
} else if (export_part == "fan_adapter") {
    _fan_wall_adapter();
} else if (export_part == "fan_wall") {
    _fan_wall();
} else {
    pi_carrier_stack_assembly();
}
