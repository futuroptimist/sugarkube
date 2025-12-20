// STL artifacts + build docs:
// - Spec: docs/pi_cluster_stack.md
// - CI workflow: https://github.com/futuroptimist/sugarkube/actions/workflows/scad-to-stl.yml
// - Artifact: stl-${GITHUB_SHA} (contains stl/pi_cluster/pi_carrier_stack_* modular parts)

// Force imports to avoid auto-rendering the base carrier from within this wrapper.
_pi_carrier_auto_render = false;

include <./pi_dimensions.scad>;

// ---- stack wrapper params ----
levels = is_undef(levels) ? 3 : levels;
z_gap_clear = is_undef(z_gap_clear) ? 32 : z_gap_clear;

export_part = is_undef(export_part) ? "assembly" : export_part;
emit_dimension_report = is_undef(emit_dimension_report) ? false : emit_dimension_report;
emit_geometry_report = is_undef(emit_geometry_report) ? false : emit_geometry_report;

// Keep these for the existing dimension echo schema.
column_spacing = is_undef(column_spacing) ? pi_hole_spacing : column_spacing;
fan_size = is_undef(fan_size) ? 120 : fan_size;

// Stack-specific defaults (wrapper-local config).
// IMPORTANT: Do not "capture" possibly-undefined vars by reading them; that triggers warnings.
// Use the standard is_undef(var) ? default : var pattern instead.
stack_plate_thickness_cfg =
    is_undef(stack_plate_thickness) ? 3.0 : stack_plate_thickness;
plate_thickness_cfg =
    is_undef(plate_thickness) ? stack_plate_thickness_cfg : plate_thickness;

stack_edge_margin_cfg =
    is_undef(stack_edge_margin) ? 15 : stack_edge_margin;
edge_margin_cfg =
    is_undef(edge_margin) ? stack_edge_margin_cfg : edge_margin;

stack_pocket_d_cfg =
    is_undef(stack_pocket_d) ? 9 : stack_pocket_d;

stack_pocket_depth_input_cfg =
    is_undef(stack_pocket_depth_input)
        ? (is_undef(stack_pocket_depth) ? 1.2 : stack_pocket_depth)
        : stack_pocket_depth_input;

stack_pocket_depth_cfg =
    is_undef(stack_pocket_depth)
        ? min(stack_pocket_depth_input_cfg, plate_thickness_cfg / 2 - 0.1)
        : stack_pocket_depth;

// Import base carrier module / helpers.
include <./pi_carrier.scad>;

// Compute carrier dimensions for centering ONLY.
// Plate dims are invariant to stack mounts, so include_stack_mounts=false is fine.
carrier_dims_layout = carrier_dimensions(
    include_stack_mounts = false,
    stack_edge_margin = stack_edge_margin_cfg,
    edge_margin = edge_margin_cfg,
    plate_thickness = plate_thickness_cfg,
    stack_pocket_depth = stack_pocket_depth_cfg,
    hole_spacing = hole_spacing,
    board_angle = board_angle,
    gap_between_boards = gap_between_boards,
    pi_positions = pi_positions,
    board_len = board_len,
    board_wid = board_wid,
    corner_radius = corner_radius,
    port_clearance = port_clearance,
    stack_pocket_d = stack_pocket_d_cfg,
    stack_mount_positions_input = stack_mount_positions
);

plate_len = carrier_plate_len(carrier_dims_layout);
plate_wid = carrier_plate_wid(carrier_dims_layout);

level_height = z_gap_clear + plate_thickness_cfg;
stack_height = (levels - 1) * level_height + plate_thickness_cfg;

module _carrier(level = 0) {
    // Preserve existing centering + spacing:
    translate([-plate_len / 2, -plate_wid / 2, level * level_height])
        pi_carrier(
            // Force stack mounts ON
            include_stack_mounts = true,

            // Ensure stack-ready plate + pockets
            plate_thickness = plate_thickness_cfg,
            stack_edge_margin = stack_edge_margin_cfg,
            edge_margin = edge_margin_cfg,
            stack_pocket_d = stack_pocket_d_cfg,
            stack_pocket_depth = stack_pocket_depth_cfg,

            emit_geometry_report = emit_geometry_report
        );
}

module pi_carrier_stack_preview_only() {
    for (level = [0 : levels - 1])
        _carrier(level);
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

// Keep export_part behavior, but preview only carriers for now.
if (export_part == "carrier_level") {
    _carrier(0);
} else {
    pi_carrier_stack_preview_only();
}
