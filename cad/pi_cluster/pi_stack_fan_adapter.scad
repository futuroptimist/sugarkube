include <./pi_dimensions.scad>;
include <./pi_carrier.scad>;

levels = is_undef(levels) ? 3 : levels;
z_gap_clear = is_undef(z_gap_clear) ? 32 : z_gap_clear;
fan_offset_from_stack = is_undef(fan_offset_from_stack) ? 15 : fan_offset_from_stack;
column_spacing = is_undef(column_spacing) ? pi_hole_spacing : column_spacing;
column_tab_offset = is_undef(column_tab_offset) ? 6 : column_tab_offset;
fan_insert_L = is_undef(fan_insert_L) ? 4.0 : fan_insert_L;
stack_bolt_d = is_undef(stack_bolt_d) ? 3.4 : stack_bolt_d;
stack_pocket_d = is_undef(stack_pocket_d) ? 8.5 : stack_pocket_d;

adapter_plate_t = is_undef(adapter_plate_t) ? 3.0 : adapter_plate_t;
spine_thickness = is_undef(spine_thickness) ? 4.0 : spine_thickness;
spine_width_extra = is_undef(spine_width_extra) ? 20 : spine_width_extra;

stack_height = levels * z_gap_clear;
spine_height = stack_height + plate_thickness;
fan_tab_depth = fan_insert_L + 6;

default_stack_mount_positions = [
    [-column_spacing[0] / 2 - fan_offset_from_stack, -column_spacing[1] / 2],
    [column_spacing[0] / 2 + fan_offset_from_stack, -column_spacing[1] / 2],
    [-column_spacing[0] / 2 - fan_offset_from_stack, column_spacing[1] / 2],
    [column_spacing[0] / 2 + fan_offset_from_stack, column_spacing[1] / 2]
];
stack_mount_positions = is_undef(stack_mount_positions)
    ? default_stack_mount_positions
    : stack_mount_positions;

function _fan_side_mounts() =
    let(sorted = sort(stack_mount_positions, function (a, b) a[0] > b[0]))
        [sorted[0], sorted[1]];

module _anchor_plate(pos) {
    translate([pos[0], pos[1], -adapter_plate_t])
        difference() {
            cylinder(h = adapter_plate_t, r = stack_pocket_d / 2 + 2.0, $fn = 80);
            translate([0, 0, -0.1])
                cylinder(h = adapter_plate_t + 0.2, r = stack_bolt_d / 2, $fn = 60);
        }
}

module _spine() {
    span = column_spacing[0] + spine_width_extra;
    translate([
        fan_offset_from_stack + column_spacing[0] / 2 - span / 2,
        -spine_thickness / 2,
        0
    ])
        cube([span, spine_thickness, spine_height]);
}

module _fan_wall_holes() {
    for (cx = [fan_offset_from_stack, fan_offset_from_stack + column_spacing[0]])
        for (level = [0 : levels - 1]) {
            z_pos = column_tab_offset + level * z_gap_clear + fan_tab_depth / 2;
            translate([cx, 0, z_pos])
                rotate([90, 0, 0])
                    cylinder(h = spine_thickness + 0.6, r = 1.6, $fn = 40);
        }
}

module pi_stack_fan_adapter() {
    anchors = _fan_side_mounts();
    union() {
        for (pos = anchors)
            _anchor_plate(pos);

        difference() {
            _spine();
            _fan_wall_holes();
        }
    }
}

pi_stack_fan_adapter();
