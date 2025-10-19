include <fan_patterns.scad>;

fan_size = is_undef(fan_size) ? 120 : fan_size;
fan_plate_t = is_undef(fan_plate_t) ? 4 : fan_plate_t;
fan_insert_od = is_undef(fan_insert_od) ? 5.0 : fan_insert_od;
fan_insert_L = is_undef(fan_insert_L) ? 4.0 : fan_insert_L;
levels = is_undef(levels) ? 3 : levels;
z_gap_clear = is_undef(z_gap_clear) ? 32 : z_gap_clear;
column_spacing = is_undef(column_spacing) ? [58, 49] : column_spacing;
column_tab_width = is_undef(column_tab_width) ? 12 : column_tab_width;
column_tab_thickness = is_undef(column_tab_thickness) ? 6 : column_tab_thickness;
column_tab_offset = is_undef(column_tab_offset) ? 6 : column_tab_offset;
include_bosses = is_undef(include_bosses) ? true : include_bosses;

fan_clearance_radius = fan_mount_clearance(fan_size) / 2;
boss_radius = fan_insert_od / 2 + 1.2;
boss_height = fan_insert_L + 0.8;
wall_width = fan_face_extent(fan_size);
stack_height = levels * z_gap_clear;
wall_height = stack_height + column_tab_offset * 2;
fan_opening = fan_size - 10;
fan_center_z = column_tab_offset + stack_height / 2;
hole_spacing = fan_hole_spacing(fan_size);

module _fan_mount(x, z) {
    if (include_bosses) {
        translate([x, fan_plate_t / 2, z])
            rotate([90, 0, 0])
                cylinder(h = boss_height, r = boss_radius, $fn = 50);
    }
}

module fan_wall(
    fan_size = fan_size,
    fan_plate_t = fan_plate_t,
    fan_insert_od = fan_insert_od,
    fan_insert_L = fan_insert_L,
    levels = levels,
    z_gap_clear = z_gap_clear,
    column_spacing = column_spacing
) {
    difference() {
        translate([-wall_width / 2, -fan_plate_t / 2, 0])
            cube([wall_width, fan_plate_t, wall_height]);

        translate([-fan_opening / 2, -fan_plate_t, fan_center_z - fan_opening / 2])
            cube([fan_opening, fan_plate_t * 2, fan_opening]);

        for (dx = [-hole_spacing / 2, hole_spacing / 2])
            for (dz = [-hole_spacing / 2, hole_spacing / 2])
                translate([dx, 0, fan_center_z + dz])
                    rotate([90, 0, 0])
                        cylinder(h = fan_plate_t + boss_height + 0.4, r = fan_clearance_radius, $fn = 40);
    }

    for (dx = [-hole_spacing / 2, hole_spacing / 2])
        for (dz = [-hole_spacing / 2, hole_spacing / 2])
            _fan_mount(dx, fan_center_z + dz);

    // Column interface tabs with M2.5 pass-through holes
    tab_depth = fan_plate_t + column_tab_thickness;
    for (cx = [-column_spacing[0] / 2, column_spacing[0] / 2]) {
        for (level = [0 : levels - 1]) {
            z_pos = column_tab_offset + level * z_gap_clear;
            difference() {
                translate([cx - column_tab_width / 2, fan_plate_t / 2, z_pos])
                    cube([column_tab_width, tab_depth, fan_insert_L + 6]);

                translate([cx, fan_plate_t / 2 + tab_depth / 2, z_pos + (fan_insert_L + 6) / 2])
                    rotate([90, 0, 0])
                        cylinder(h = tab_depth + 0.4, r = 1.6, $fn = 30);
            }
        }
    }
}

fan_wall();
