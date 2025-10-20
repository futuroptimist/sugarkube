_pi_carrier_auto_render = false;
include <pi_carrier.scad>;
use <pi_carrier_column.scad>;
use <fan_wall.scad>;

levels = is_undef(levels) ? 3 : levels;
z_gap_clear = is_undef(z_gap_clear) ? 32 : z_gap_clear;
column_mode = is_undef(column_mode) ? "printed" : column_mode;
column_od = is_undef(column_od) ? 12 : column_od;
column_wall = is_undef(column_wall) ? 2.4 : column_wall;
carrier_insert_od = is_undef(carrier_insert_od) ? 3.5 : carrier_insert_od;
carrier_insert_L = is_undef(carrier_insert_L) ? 4.0 : carrier_insert_L;
fan_size = is_undef(fan_size) ? 120 : fan_size;
fan_plate_t = is_undef(fan_plate_t) ? 4 : fan_plate_t;
fan_insert_od = is_undef(fan_insert_od) ? 5.0 : fan_insert_od;
fan_insert_L = is_undef(fan_insert_L) ? 4.0 : fan_insert_L;
fan_offset_from_stack = is_undef(fan_offset_from_stack) ? 15 : fan_offset_from_stack;
column_spacing = is_undef(column_spacing) ? pi_hole_spacing : column_spacing;
export_part = is_undef(export_part) ? "assembly" : export_part;
stack_standoff_mode = is_undef(standoff_mode) ? "heatset" : standoff_mode;
emit_dimension_report =
    is_undef(emit_dimension_report) ? false : emit_dimension_report;
alignment_guard_enabled =
    is_undef(alignment_guard_enabled) ? true : alignment_guard_enabled;
column_alignment_tolerance =
    is_undef(column_alignment_tolerance) ? 0.2 : column_alignment_tolerance;
expected_column_spacing = [58, 49];

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

module _carrier(level) {
    translate([-plate_len / 2, -plate_wid / 2, level * z_gap_clear])
        let(standoff_mode = stack_standoff_mode) pi_carrier();
}

module _columns() {
    for (x = [-column_spacing[0] / 2, column_spacing[0] / 2])
        for (y = [-column_spacing[1] / 2, column_spacing[1] / 2])
            translate([x, y, 0])
                pi_carrier_column(
                    column_mode = column_mode,
                    levels = levels,
                    z_gap_clear = z_gap_clear,
                    column_od = column_od,
                    column_wall = column_wall,
                    carrier_insert_od = carrier_insert_od,
                    carrier_insert_L = carrier_insert_L,
                    emit_dimension_report = emit_dimension_report
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
    _columns();
    for (level = [0 : levels - 1])
        _carrier(level);
    _fan_wall();
}

if (emit_dimension_report) {
    stack_height = levels * z_gap_clear;
    echo(
        "pi_carrier_stack",
        levels = levels,
        fan_size = fan_size,
        column_mode = column_mode,
        column_spacing = column_spacing,
        stack_height = stack_height,
        export_part = export_part
    );
}

if (export_part == "columns") {
    pi_carrier_column(
        column_mode = column_mode,
        levels = levels,
        z_gap_clear = z_gap_clear,
        column_od = column_od,
        column_wall = column_wall,
        carrier_insert_od = carrier_insert_od,
        carrier_insert_L = carrier_insert_L,
        emit_dimension_report = emit_dimension_report
    );
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
