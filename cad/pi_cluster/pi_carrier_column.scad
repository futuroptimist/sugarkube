column_mode = is_undef(column_mode) ? "printed" : column_mode;
levels = is_undef(levels) ? 3 : levels;
z_gap_clear = is_undef(z_gap_clear) ? 32 : z_gap_clear;
column_od = is_undef(column_od) ? 12 : column_od;
column_wall = is_undef(column_wall) ? 2.4 : column_wall;
carrier_insert_od = is_undef(carrier_insert_od) ? 3.5 : carrier_insert_od;
carrier_insert_L = is_undef(carrier_insert_L) ? 4.0 : carrier_insert_L;
foot_diameter = is_undef(foot_diameter) ? 22 : foot_diameter;
foot_height = is_undef(foot_height) ? 3 : foot_height;
cap_height = is_undef(cap_height) ? 3 : cap_height;

column_radius = column_od / 2;
inner_radius = column_radius - column_wall;
column_height = levels * z_gap_clear + cap_height;

module _column_shell() {
    union() {
        cylinder(h = foot_height, r = foot_diameter / 2, $fn = 60);
        translate([0, 0, foot_height])
            cylinder(h = column_height, r = column_radius, $fn = 70);
    }
}

module _column_interior() {
    if (column_mode == "printed") {
        translate([0, 0, foot_height + 1])
            cylinder(h = column_height - 2, r = max(inner_radius, 1.2), $fn = 60);
    } else {
        translate([0, 0, foot_height])
            cylinder(h = column_height, r = carrier_insert_od / 2 + 0.6, $fn = 50);
    }
}

module _column_radial_bores() {
    for (level = [0 : levels - 1]) {
        z_pos = foot_height + level * z_gap_clear + carrier_insert_L / 2;
        translate([0, 0, z_pos])
            rotate([0, 90, 0])
                cylinder(h = column_od + 4, r = carrier_insert_od / 2, $fn = 40);
    }
}

module pi_carrier_column(
    column_mode = column_mode,
    levels = levels,
    z_gap_clear = z_gap_clear,
    column_od = column_od,
    column_wall = column_wall,
    carrier_insert_od = carrier_insert_od,
    carrier_insert_L = carrier_insert_L
) {
    difference() {
        _column_shell();
        union() {
            _column_interior();
            _column_radial_bores();
        }
    }

    // Add a locating chamfer on top for easier carrier placement.
    translate([0, 0, foot_height + column_height - 1])
        cylinder(h = 1.2, r1 = column_radius - 0.6, r2 = column_radius, $fn = 60);
}

pi_carrier_column();
