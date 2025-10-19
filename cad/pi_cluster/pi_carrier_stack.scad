use <pi_carrier.scad>;
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
column_spacing = is_undef(column_spacing) ? [58, 49] : column_spacing;
export_part = is_undef(export_part) ? "assembly" : export_part;

plate_dimensions = pi_carrier_plate_size();
plate_len = plate_dimensions[0];
plate_wid = plate_dimensions[1];
plate_thickness = plate_dimensions[2];

function _column_mode_to_standoff(mode) = mode == "printed" ? "printed" : "heatset";

echo(str(
    "pi_carrier_stack",
    " levels=", levels,
    " fan_size=", fan_size,
    " column_mode=", column_mode
));

module _carrier(level) {
    translate([0, 0, level * z_gap_clear])
        translate([-plate_len / 2, -plate_wid / 2, -plate_thickness / 2])
            let(standoff_mode = _column_mode_to_standoff(column_mode))
                pi_carrier();
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
                    carrier_insert_L = carrier_insert_L
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
            column_spacing = column_spacing
        );
}

module pi_carrier_stack_assembly() {
    _columns();
    for (level = [0 : levels - 1])
        _carrier(level);
    _fan_wall();
}

if (export_part == "columns") {
    pi_carrier_column(
        column_mode = column_mode,
        levels = levels,
        z_gap_clear = z_gap_clear,
        column_od = column_od,
        column_wall = column_wall,
        carrier_insert_od = carrier_insert_od,
        carrier_insert_L = carrier_insert_L
    );
} else if (export_part == "fan_wall") {
    fan_wall(
        fan_size = fan_size,
        fan_plate_t = fan_plate_t,
        fan_insert_od = fan_insert_od,
        fan_insert_L = fan_insert_L,
        levels = levels,
        z_gap_clear = z_gap_clear,
        column_spacing = column_spacing
    );
} else {
    pi_carrier_stack_assembly();
}
