include <./pi_dimensions.scad>;

_pi_carrier_auto_render = false;
include <./pi_carrier.scad>;

// Fan adapter config defaults (wrapper-local).
stack_bolt_d_cfg = is_undef(stack_bolt_d) ? 3.4 : stack_bolt_d;
stack_pocket_d_cfg = is_undef(stack_pocket_d) ? 9 : stack_pocket_d;
stack_pocket_depth_cfg = is_undef(stack_pocket_depth) ? 1.2 : stack_pocket_depth;
levels_cfg = is_undef(levels) ? 3 : levels;
z_gap_clear_cfg = is_undef(z_gap_clear) ? 32 : z_gap_clear;
plate_thickness_cfg = is_undef(plate_thickness) ? 2.0 : plate_thickness;
stack_edge_margin_cfg = is_undef(stack_edge_margin) ? 15 : stack_edge_margin;
edge_margin_cfg = is_undef(edge_margin) ? stack_edge_margin_cfg : edge_margin;
column_spacing_cfg = is_undef(column_spacing) ? pi_hole_spacing : column_spacing;
adapter_thickness_cfg = is_undef(adapter_thickness) ? 8 : adapter_thickness;
interface_extension_cfg = is_undef(interface_extension) ? 10 : interface_extension;
interface_hole_d_cfg = is_undef(interface_hole_d) ? 3.2 : interface_hole_d;

// Resolve carrier geometry to derive stack mount positions when not provided explicitly.
stack_mount_positions_input_safe =
    is_undef(stack_mount_positions) ? undef : stack_mount_positions;

carrier_dims_layout = carrier_dimensions(
    include_stack_mounts = true,
    stack_edge_margin = stack_edge_margin_cfg,
    edge_margin = edge_margin_cfg,
    plate_thickness = plate_thickness_cfg,
    stack_pocket_d = stack_pocket_d_cfg,
    stack_pocket_depth = stack_pocket_depth_cfg,
    hole_spacing = hole_spacing,
    board_angle = board_angle,
    gap_between_boards = gap_between_boards,
    pi_positions = pi_positions,
    board_len = board_len,
    board_wid = board_wid,
    corner_radius = corner_radius,
    port_clearance = port_clearance,
    stack_mount_positions_input = stack_mount_positions_input_safe
);

stack_mount_positions_resolved = carrier_stack_mount_positions(carrier_dims_layout);
stack_mount_positions_final = is_undef(stack_mount_positions)
    ? stack_mount_positions_resolved
    : stack_mount_positions;

module pi_stack_fan_adapter(
    stack_bolt_d = stack_bolt_d_cfg,
    stack_pocket_d = stack_pocket_d_cfg,
    stack_pocket_depth = stack_pocket_depth_cfg,
    levels = levels_cfg,
    z_gap_clear = z_gap_clear_cfg,
    plate_thickness = plate_thickness_cfg,
    column_spacing = column_spacing_cfg,
    adapter_thickness = adapter_thickness_cfg,
    interface_extension = interface_extension_cfg,
    interface_hole_d = interface_hole_d_cfg,
    stack_mount_positions = stack_mount_positions_final
) {
    assert(
        len(stack_mount_positions) > 0,
        "stack_mount_positions must align with carrier stack pockets"
    );

    level_height = z_gap_clear + plate_thickness;
    stack_height = (levels - 1) * level_height + plate_thickness;

    fan_side_x = max([for (p = stack_mount_positions) p[0]]);
    fan_side_positions = [for (p = stack_mount_positions) if (p[0] >= fan_side_x - 0.01) p];
    assert(len(fan_side_positions) == 2, "expected exactly two fan-side posts");
    fan_side_span = max([for (p = fan_side_positions) p[1]]) - min([for (p = fan_side_positions) p[1]]);
    body_span_y = fan_side_span + 20;
    body_height = stack_height;
    center_y = (max([for (p = fan_side_positions) p[1]]) + min([for (p = fan_side_positions) p[1]])) / 2;

    interface_offsets = [for (pos = fan_side_positions) pos[1]];
    interface_levels = [for (level = [0 : levels - 1]) stack_pocket_depth + level * level_height];

    module _post_hole(pos_y) {
        translate([adapter_thickness / 2, pos_y - center_y, 0])
            cylinder(h = body_height + 0.02, r = stack_bolt_d / 2, $fn = 60);

        translate([adapter_thickness / 2, pos_y - center_y, -0.01])
            cylinder(h = stack_pocket_depth + 0.02, r = stack_pocket_d / 2 + 0.3, $fn = 70);
    }

    module _fan_interface() {
        translate([adapter_thickness, -body_span_y / 2, 0])
            cube([interface_extension, body_span_y, body_height]);

        for (x_off = interface_offsets)
        for (z = interface_levels)
            translate([adapter_thickness + interface_extension / 2, x_off - center_y, z])
                rotate([0, 90, 0])
                    cylinder(h = interface_extension + 0.2, r = interface_hole_d / 2, $fn = 50);
    }

    difference() {
        union() {
            translate([0, -body_span_y / 2, 0])
                cube([adapter_thickness, body_span_y, body_height]);
            _fan_interface();
        }

        for (pos = fan_side_positions)
            _post_hole(pos[1]);
    }
}

pi_stack_fan_adapter();
