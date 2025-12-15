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
stack_edge_margin = is_undef(stack_edge_margin) ? 15 : stack_edge_margin;
stack_bolt_d = is_undef(stack_bolt_d) ? 3.4 : stack_bolt_d;
stack_pocket_d = is_undef(stack_pocket_d) ? 8.5 : stack_pocket_d;
stack_pocket_depth = is_undef(stack_pocket_depth) ? 1.0 : stack_pocket_depth;
stack_mount_positions =
    is_undef(stack_mount_positions) ? default_stack_mount_positions
                                    : stack_mount_positions;
export_part = is_undef(export_part) ? "assembly" : export_part;
stack_standoff_mode = is_undef(standoff_mode) ? "heatset" : standoff_mode;
emit_dimension_report =
    is_undef(emit_dimension_report) ? false : emit_dimension_report;
alignment_guard_enabled =
    is_undef(alignment_guard_enabled) ? true : alignment_guard_enabled;
column_alignment_tolerance =
    is_undef(column_alignment_tolerance) ? 0.2 : column_alignment_tolerance;
expected_column_spacing = pi_hole_spacing;

if (alignment_guard_enabled) {
    assert(
        abs(column_spacing[0] - expected_column_spacing[0]) <=
            column_alignment_tolerance,
        str(
            "column_spacing[0] out of tolerance (",
            column_spacing[0],
            " mm)"
        )
    );
    assert(
        abs(column_spacing[1] - expected_column_spacing[1]) <=
            column_alignment_tolerance,
        str(
            "column_spacing[1] out of tolerance (",
            column_spacing[1],
            " mm)"
        )
    );
}

module carrier_level_plate() {
    let(
        standoff_mode = stack_standoff_mode,
        include_stack_mounts = true,
        stack_edge_margin = stack_edge_margin,
        stack_mount_positions = stack_mount_positions,
        stack_bolt_d = stack_bolt_d,
        stack_pocket_d = stack_pocket_d,
        stack_pocket_depth = stack_pocket_depth
    ) pi_carrier();
}

module _carrier(level) {
    translate([-plate_len / 2, -plate_wid / 2, level * z_gap_clear])
        carrier_level_plate();
}

module _stack_posts() {
    for (level = [0 : levels - 2])
        for (pos = stack_mount_positions)
            translate([pos[0], pos[1], level * z_gap_clear])
                pi_stack_post(
                    stack_bolt_d = stack_bolt_d,
                    stack_pocket_d = stack_pocket_d,
                    stack_pocket_depth = stack_pocket_depth,
                    z_gap_clear = z_gap_clear,
                    plate_thickness = plate_thickness
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

module _fan_adapter() {
    pi_stack_fan_adapter(
        levels = levels,
        z_gap_clear = z_gap_clear,
        fan_offset_from_stack = fan_offset_from_stack,
        column_spacing = column_spacing,
        fan_insert_L = fan_insert_L,
        stack_bolt_d = stack_bolt_d,
        stack_pocket_d = stack_pocket_d,
        stack_mount_positions = stack_mount_positions
    );
}

module pi_carrier_stack_assembly() {
    _stack_posts();
    for (level = [0 : levels - 1])
        _carrier(level);
    _fan_adapter();
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
        stack_mount_positions = stack_mount_positions,
        export_part = export_part
    );
}

if (export_part == "carrier_level") {
    carrier_level_plate();
} else if (export_part == "post") {
    pi_stack_post(
        stack_bolt_d = stack_bolt_d,
        stack_pocket_d = stack_pocket_d,
        stack_pocket_depth = stack_pocket_depth,
        z_gap_clear = z_gap_clear,
        plate_thickness = plate_thickness
    );
} else if (export_part == "fan_adapter") {
    _fan_adapter();
} else if (export_part == "fan_wall") {
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
} else {
    pi_carrier_stack_assembly();
}
