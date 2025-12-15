include <./pi_dimensions.scad>;
include <./fan_patterns.scad>;

levels = is_undef(levels) ? 3 : levels;
z_gap_clear = is_undef(z_gap_clear) ? 32 : z_gap_clear;
stack_mount_positions = is_undef(stack_mount_positions)
    ? [[50, 50], [-50, 50], [50, -50], [-50, -50]]
    : stack_mount_positions;
stack_bolt_d = is_undef(stack_bolt_d) ? 3.4 : stack_bolt_d;
stack_pocket_d = is_undef(stack_pocket_d) ? 8 : stack_pocket_d;
stack_pocket_depth = is_undef(stack_pocket_depth) ? 1.6 : stack_pocket_depth;
column_spacing = is_undef(column_spacing) ? pi_hole_spacing : column_spacing;
fan_offset_from_stack = is_undef(fan_offset_from_stack) ? 15 : fan_offset_from_stack;
fan_insert_od = is_undef(fan_insert_od) ? 5.0 : fan_insert_od;
fan_insert_L = is_undef(fan_insert_L) ? 4.0 : fan_insert_L;
adapter_thickness = is_undef(adapter_thickness) ? 6 : adapter_thickness;
adapter_margin = is_undef(adapter_margin) ? 6 : adapter_margin;
column_tab_offset = is_undef(column_tab_offset) ? 6 : column_tab_offset;

stack_height = levels * z_gap_clear;
plate_height = stack_height + adapter_margin * 2;
plate_width = column_spacing[0] + adapter_margin * 2;
mount_plane_y = fan_offset_from_stack;

function _fan_side_mounts() =
    let(max_x = max([for (p = stack_mount_positions) p[0]]))
        [for (p = stack_mount_positions) if (p[0] == max_x) p];

function _clamp_pairs() =
    let(
        fan_side = _fan_side_mounts(),
        min_y = len(fan_side) > 0 ? min([for (p = fan_side) p[1]]) : 0,
        max_y = len(fan_side) > 0 ? max([for (p = fan_side) p[1]]) : 0,
        min_idx = len(fan_side) > 0 ? search(min_y, [for (p = fan_side) p[1]])[0] : 0,
        max_idx = len(fan_side) > 0 ? search(max_y, [for (p = fan_side) p[1]])[0] : 0,
        min_pos = len(fan_side) > 0 ? fan_side[min_idx] : [0, 0],
        max_pos = len(fan_side) > 0 ? fan_side[max_idx] : [0, 0]
    )
    len(fan_side) == 0 ? [] : len(fan_side) == 1 ? fan_side : [min_pos, max_pos];

module _mount_block(pos=[0,0]) {
    translate([pos[0], pos[1], stack_pocket_depth])
        cube([adapter_thickness, adapter_thickness, stack_height], center = true);
}

module _stack_mount_clearance(pos=[0,0]) {
    translate([pos[0], pos[1], 0])
        cylinder(h = stack_pocket_depth + adapter_margin, r = stack_pocket_d / 2, $fn = 80);
    translate([pos[0], pos[1], -0.2])
        cylinder(h = plate_height + 0.4, r = stack_bolt_d / 2, $fn = 50);
}

module _fan_interface() {
    boss_radius = fan_insert_od / 2 + 1.0;
    for (level = [0 : levels - 1]) {
        z_pos = column_tab_offset + level * z_gap_clear;
        for (cx = [-column_spacing[0] / 2, column_spacing[0] / 2]) {
            translate([cx, mount_plane_y + adapter_thickness / 2, z_pos])
                rotate([90, 0, 0])
                    difference() {
                        cylinder(h = adapter_thickness, r = boss_radius, $fn = 60);
                        cylinder(h = adapter_thickness + 0.4, r = fan_insert_od / 2, $fn = 40);
                    }
        }
    }
}

module stack_fan_adapter() {
    clamp_positions = _clamp_pairs();
    difference() {
        union() {
            translate([0, mount_plane_y, plate_height / 2 - adapter_margin])
                cube([plate_width, adapter_thickness, plate_height], center = true);
            for (pos = clamp_positions)
                _mount_block(pos);
        }
        for (pos = clamp_positions)
            _stack_mount_clearance(pos);
    }

    _fan_interface();
}

stack_fan_adapter();
