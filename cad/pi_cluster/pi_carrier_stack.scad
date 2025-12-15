// STL artifacts + build docs:
// - Spec: docs/pi_cluster_stack.md
// - CI workflow: https://github.com/futuroptimist/sugarkube/actions/workflows/scad-to-stl.yml
// - Artifact: stl-${GITHUB_SHA}
_pi_carrier_auto_render = false;
include <./pi_dimensions.scad>;
include <./pi_carrier.scad>;
use <./fan_wall.scad>;
use <./pi_stack_post.scad>;
use <./pi_stack_fan_adapter.scad>;

levels = is_undef(levels) ? 3 : levels;
z_gap_clear = is_undef(z_gap_clear) ? 32 : z_gap_clear;
export_part = is_undef(export_part) ? "assembly" : export_part;
fan_size = is_undef(fan_size) ? 120 : fan_size;
fan_plate_t = is_undef(fan_plate_t) ? 4 : fan_plate_t;
fan_insert_od = is_undef(fan_insert_od) ? 5.0 : fan_insert_od;
fan_insert_L = is_undef(fan_insert_L) ? 4.0 : fan_insert_L;
fan_offset_from_stack = is_undef(fan_offset_from_stack) ? 15 : fan_offset_from_stack;
standoff_mode = is_undef(standoff_mode) ? "heatset" : standoff_mode;
stack_edge_margin = is_undef(stack_edge_margin) ? 15 : stack_edge_margin;
stack_bolt_d = is_undef(stack_bolt_d) ? 3.4 : stack_bolt_d;
stack_pocket_d = is_undef(stack_pocket_d) ? 8 : stack_pocket_d;
stack_pocket_depth = is_undef(stack_pocket_depth) ? 1.6 : stack_pocket_depth;
stack_mount_positions = is_undef(stack_mount_positions) ? undef : stack_mount_positions;
emit_dimension_report =
    is_undef(emit_dimension_report) ? false : emit_dimension_report;

pi_positions = [[0,0], [1,0], [0,1]];
board_len = 85;
board_wid = 56;
hole_spacing = pi_hole_spacing;
gap_between_boards = 10;
board_angle = 0;
port_clearance = 6;
edge_margin = stack_edge_margin;

rotX = abs(board_len*cos(board_angle)) + abs(board_wid*sin(board_angle));
rotY = abs(board_len*sin(board_angle)) + abs(board_wid*cos(board_angle));
board_spacing_x = rotX + gap_between_boards;
board_spacing_y = rotY + gap_between_boards;
max_x = max([for(p=pi_positions) p[0]]);
max_y = max([for(p=pi_positions) p[1]]);
plate_len = (max_x+1)*rotX + max_x*gap_between_boards + 2*edge_margin;
plate_wid = (max_y+1)*rotY + max_y*gap_between_boards + 2*edge_margin + 2*port_clearance;

function stack_mount_defaults() = [
    [ plate_len / 2 - stack_edge_margin,  plate_wid / 2 - stack_edge_margin],
    [-plate_len / 2 + stack_edge_margin,  plate_wid / 2 - stack_edge_margin],
    [ plate_len / 2 - stack_edge_margin, -plate_wid / 2 + stack_edge_margin],
    [-plate_len / 2 + stack_edge_margin, -plate_wid / 2 + stack_edge_margin]
];

resolved_stack_mount_positions =
    is_undef(stack_mount_positions) ? stack_mount_defaults() : stack_mount_positions;

module carrier_level(z_pos = 0) {
    translate([-plate_len / 2, -plate_wid / 2, z_pos])
        pi_carrier(
            include_stack_mounts = true,
            stack_edge_margin = stack_edge_margin,
            stack_mount_positions = stack_mount_positions,
            stack_bolt_d = stack_bolt_d,
            stack_pocket_d = stack_pocket_d,
            stack_pocket_depth = stack_pocket_depth,
            standoff_mode = standoff_mode
        );
}

module stack_posts() {
    for (pos = resolved_stack_mount_positions)
        for (level = [0 : levels - 2])
            translate([pos[0], pos[1], level * z_gap_clear])
                stack_post(
                    stack_bolt_d = stack_bolt_d,
                    stack_pocket_d = stack_pocket_d,
                    stack_pocket_depth = stack_pocket_depth,
                    z_gap_clear = z_gap_clear
                );
}

module fan_adapter() {
    stack_fan_adapter(
        levels = levels,
        z_gap_clear = z_gap_clear,
        stack_mount_positions = resolved_stack_mount_positions,
        stack_bolt_d = stack_bolt_d,
        stack_pocket_d = stack_pocket_d,
        stack_pocket_depth = stack_pocket_depth,
        column_spacing = pi_hole_spacing,
        fan_offset_from_stack = fan_offset_from_stack,
        fan_insert_od = fan_insert_od,
        fan_insert_L = fan_insert_L
    );
}

module fan_wall_part() {
    translate([plate_len / 2 + fan_offset_from_stack, 0, 0])
        fan_wall(
            fan_size = fan_size,
            fan_plate_t = fan_plate_t,
            fan_insert_od = fan_insert_od,
            fan_insert_L = fan_insert_L,
            levels = levels,
            z_gap_clear = z_gap_clear,
            column_spacing = pi_hole_spacing,
            emit_dimension_report = emit_dimension_report
        );
}

module pi_carrier_stack_assembly() {
    stack_posts();
    for (level = [0 : levels - 1])
        carrier_level(level * z_gap_clear);
    fan_adapter();
    fan_wall_part();
}

if (emit_dimension_report) {
    stack_height = levels * z_gap_clear;
    echo(
        "pi_carrier_stack",
        levels = levels,
        fan_size = fan_size,
        stack_height = stack_height,
        export_part = export_part
    );
}

if (export_part == "carrier_level") {
    carrier_level();
} else if (export_part == "post") {
    stack_post(
        stack_bolt_d = stack_bolt_d,
        stack_pocket_d = stack_pocket_d,
        stack_pocket_depth = stack_pocket_depth,
        z_gap_clear = z_gap_clear
    );
} else if (export_part == "fan_adapter") {
    fan_adapter();
} else if (export_part == "fan_wall") {
    fan_wall_part();
} else {
    pi_carrier_stack_assembly();
}
