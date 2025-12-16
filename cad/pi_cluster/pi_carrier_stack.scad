// STL artifacts + build docs:
// - Spec: docs/pi_cluster_stack.md
// - CI workflow: https://github.com/futuroptimist/sugarkube/actions/workflows/scad-to-stl.yml
// - Artifact: stl-${GITHUB_SHA} (contains stl/pi_cluster/pi_carrier_stack_* modular parts)

// Force imports to avoid auto-rendering the base carrier from within this wrapper.
_pi_carrier_auto_render = false;

// Stack overrides that feed into the base carrier before inclusion.
stack_edge_margin = is_undef(stack_edge_margin) ? 15 : stack_edge_margin;
edge_margin = is_undef(edge_margin) ? stack_edge_margin : edge_margin;
include_stack_mounts = true;

stack_bolt_d = is_undef(stack_bolt_d) ? 3.4 : stack_bolt_d;
stack_pocket_d = is_undef(stack_pocket_d) ? 8 : stack_pocket_d;
stack_pocket_depth_input = is_undef(stack_pocket_depth) ? 1.2 : stack_pocket_depth;
adapter_thickness = is_undef(adapter_thickness) ? 8 : adapter_thickness;
stack_plate_thickness = is_undef(stack_plate_thickness) ? 3.0 : stack_plate_thickness;
plate_thickness = is_undef(plate_thickness) ? stack_plate_thickness : plate_thickness;
stack_pocket_depth = min(stack_pocket_depth_input, plate_thickness / 2 - 0.01);

include <./pi_dimensions.scad>;
// Shared spacing + fan defaults
levels = is_undef(levels) ? 3 : levels;
z_gap_clear = is_undef(z_gap_clear) ? 32 : z_gap_clear;
column_spacing = is_undef(column_spacing) ? pi_hole_spacing : column_spacing;
fan_size = is_undef(fan_size) ? 120 : fan_size;
fan_plate_t = is_undef(fan_plate_t) ? 4 : fan_plate_t;
fan_insert_od = is_undef(fan_insert_od) ? 5.0 : fan_insert_od;
fan_insert_L = is_undef(fan_insert_L) ? 4.0 : fan_insert_L;
fan_offset_from_stack = is_undef(fan_offset_from_stack) ? 15 : fan_offset_from_stack;
alignment_guard_enabled = is_undef(alignment_guard_enabled) ? true : alignment_guard_enabled;
column_alignment_tolerance =
    is_undef(column_alignment_tolerance) ? 0.2 : column_alignment_tolerance;
expected_column_spacing = pi_hole_spacing;

export_part = is_undef(export_part) ? "assembly" : export_part;
emit_dimension_report = is_undef(emit_dimension_report) ? false : emit_dimension_report;

include <./pi_carrier.scad>;
use <./pi_stack_post.scad>;
use <./pi_stack_fan_adapter.scad>;
use <./fan_wall.scad>;

carrier_stack_mount_positions = stack_mount_positions;
level_height = z_gap_clear + plate_thickness;
stack_height = (levels - 1) * level_height + plate_thickness;

if (alignment_guard_enabled) {
    assert(
        abs(column_spacing[0] - expected_column_spacing[0]) <=
            column_alignment_tolerance,
        str(
            "column_spacing[0] out of tolerance (", column_spacing[0], " mm)"
        )
    );
    assert(
        abs(column_spacing[1] - expected_column_spacing[1]) <=
            column_alignment_tolerance,
        str(
            "column_spacing[1] out of tolerance (", column_spacing[1], " mm)"
        )
    );
}

module _carrier(level = 0) {
    translate([-plate_len / 2, -plate_wid / 2, level * level_height])
        let(
            include_stack_mounts = true,
            stack_edge_margin = stack_edge_margin,
            stack_mount_positions = carrier_stack_mount_positions,
            stack_bolt_d = stack_bolt_d,
            stack_pocket_d = stack_pocket_d,
            stack_pocket_depth = stack_pocket_depth
        ) pi_carrier();
}

module _posts() {
    for (level = [0 : levels - 2])
        for (pos = carrier_stack_mount_positions)
            translate([
                pos[0],
                pos[1],
                level * level_height + plate_thickness + z_gap_clear / 2
            ])
                pi_stack_post(
                    stack_bolt_d = stack_bolt_d,
                    stack_pocket_d = stack_pocket_d,
                    stack_pocket_depth = stack_pocket_depth,
                    z_gap_clear = z_gap_clear,
                    plate_thickness = plate_thickness
                );
}

module _fan_adapter() {
    fan_side_x = max([for (p = carrier_stack_mount_positions) p[0]]);
    translate([fan_side_x - adapter_thickness / 2, 0, 0])
        pi_stack_fan_adapter(
            stack_bolt_d = stack_bolt_d,
            stack_pocket_d = stack_pocket_d,
            stack_pocket_depth = stack_pocket_depth,
            levels = levels,
            z_gap_clear = z_gap_clear,
            plate_thickness = plate_thickness,
            column_spacing = column_spacing,
            stack_mount_positions = carrier_stack_mount_positions
        );
}

module _fan_wall() {
    fan_side_x = max([for (p = carrier_stack_mount_positions) p[0]]);
    translate([fan_side_x + fan_offset_from_stack, 0, 0])
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
    _fan_adapter();
    _fan_wall();
}

if (emit_dimension_report) {
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
        z_gap_clear = z_gap_clear,
        plate_thickness = plate_thickness
    );
} else if (export_part == "fan_adapter") {
    _fan_adapter();
} else if (export_part == "fan_wall") {
    _fan_wall();
} else {
    pi_carrier_stack_assembly();
}
