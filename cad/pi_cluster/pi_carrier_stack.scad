// cad/pi_cluster/pi_carrier_stack.scad
// STL artifacts + build docs:
// - Spec: docs/pi_cluster_stack.md
// - CI workflow: https://github.com/futuroptimist/sugarkube/actions/workflows/scad-to-stl.yml
// - Artifact: stl-${GITHUB_SHA} (contains stl/pi_cluster/pi_carrier_stack_* modular parts)
//
// CLI examples (Linux/macOS / bash):
//   openscad -o /tmp/pi_carrier_stack_level.stl \
//     -D export_part="carrier_level" \
//     -- cad/pi_cluster/pi_carrier_stack.scad
//   openscad -o /tmp/pi_carrier_stack_post.stl \
//     -D export_part="post" \
//     -- cad/pi_cluster/pi_carrier_stack.scad
//
// CLI examples (Windows PowerShell):
//   openscad `
//     -o "$env:TEMP\pi_carrier_stack_level.stl" `
//     -D 'export_part="carrier_level"' `
//     -- cad/pi_cluster/pi_carrier_stack.scad
//   openscad `
//     -o "$env:TEMP\pi_carrier_stack_post.stl" `
//     -D 'export_part="post"' `
//     -- cad/pi_cluster/pi_carrier_stack.scad

// Thin wrapper only:
// - This file must not introduce any novel geometry.
// - It must only arrange geometry from:
//   - pi_carrier.scad (carrier plates)
//   - pi_stack_post.scad (corner posts)

_pi_carrier_auto_render = false;

include <./pi_dimensions.scad>;

// ---- stack wrapper params ----
levels = is_undef(levels) ? 3 : levels;
z_gap_clear = is_undef(z_gap_clear) ? 32 : z_gap_clear;

// Part selectors are string-based to keep CLI quoting predictable across shells.
// Provide matching globals so CLI arguments like `-D export_part=carrier_level` (without quotes)
// can still resolve to the intended string token instead of remaining as undefined identifiers.
export_part_carrier_level = "carrier_level";
export_part_post = "post";
export_part_assembly = "assembly";

_cli_alias_carrier_level = export_part_carrier_level;
_cli_alias_post = export_part_post;
_cli_alias_assembly = export_part_assembly;

// Keep bare identifiers available for CLI compatibility while namespaced aliases document intent.
carrier_level = _cli_alias_carrier_level;
post = _cli_alias_post;
assembly = _cli_alias_assembly;

export_part_resolved =
    is_undef(export_part)
        ? export_part_assembly
        : (is_string(export_part) ? export_part : str(export_part));

emit_dimension_report = is_undef(emit_dimension_report) ? false : emit_dimension_report;
emit_geometry_report = is_undef(emit_geometry_report) ? false : emit_geometry_report;

// Keep these for the existing dimension echo schema.
column_spacing = is_undef(column_spacing) ? pi_hole_spacing : column_spacing;
fan_size = is_undef(fan_size) ? 120 : fan_size;

// ---- stack clamp bolt diameter (now M3 by default) ----
// IMPORTANT: do NOT assign `stack_bolt_d` globally here; pi_carrier.scad defines it too,
// and OpenSCAD warns on "overwritten" even when the value is effectively the same.
// We instead inject stack_bolt_d via `let(stack_bolt_d=...)` at the call site.
stack_bolt_d_cfg = is_undef(stack_bolt_d) ? 3.4 : stack_bolt_d;

// Stack-specific defaults (wrapper-local config).
stack_plate_thickness_cfg =
    is_undef(stack_plate_thickness) ? 3.0 : stack_plate_thickness;
plate_thickness_cfg =
    is_undef(plate_thickness) ? stack_plate_thickness_cfg : plate_thickness;

stack_edge_margin_cfg =
    is_undef(stack_edge_margin) ? 15 : stack_edge_margin;
edge_margin_cfg =
    is_undef(edge_margin) ? stack_edge_margin_cfg : edge_margin;

// Must match pi_stack_post / carrier stack-mount geometry
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

// Post tuning params (optional).
post_body_d_cfg =
    is_undef(post_body_d) ? 26 : post_body_d;
post_overhang_cfg =
    is_undef(post_overhang) ? 5 : post_overhang;
post_fit_clearance_cfg =
    is_undef(post_fit_clearance) ? 0.2 : post_fit_clearance;
post_leadin_depth_cfg =
    is_undef(post_leadin_depth) ? 0.8 : post_leadin_depth;
post_leadin_extra_clearance_cfg =
    is_undef(post_leadin_extra_clearance) ? 0.4 : post_leadin_extra_clearance;

// Mixed-corner feature orientation override.
// Default: 180° (flip wedge/tetra "opening" direction) ONLY for mixed-sign corners.
mixed_corner_feature_twist_deg_cfg =
    is_undef(mixed_corner_feature_twist_deg) ? 180 : mixed_corner_feature_twist_deg;

// Import base carrier module / helpers.
include <./pi_carrier.scad>;

// Import the post module as a library.
// `use` imports modules + functions but does NOT execute top-level assignments.
use <./pi_stack_post.scad>;

// -----------------------------------------------------------------------------
// Preview stabilization:
//
// Some OpenSCAD view modes (and deep difference() trees) can display internal CSG
// cutters/subtractions in a way that looks like "duplicate/corrupted" geometry.
// Force CGAL mesh generation for interactive preview only.
//
// - In preview (F5): $preview is true → optional render() runs.
// - In render/export (F6): $preview is false → render() is skipped (no perf hit).
//
// You can disable this by setting `preview_cgal=false` (CLI -D or customizer).
preview_cgal = is_undef(preview_cgal) ? true : preview_cgal;

module _maybe_render(convexity = 10) {
    if ($preview && preview_cgal)
        render(convexity = convexity) children();
    else
        children();
}
// -----------------------------------------------------------------------------


// Compute carrier dimensions for centering and stack-mount placement.
// Plate dims are invariant to stack mounts, so one call with include_stack_mounts=true is fine.
stack_mount_positions_input_safe =
    is_undef(stack_mount_positions) ? undef : stack_mount_positions;

carrier_dims_layout = carrier_dimensions(
    include_stack_mounts = true,
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
    stack_mount_positions_input = stack_mount_positions_input_safe
);

plate_len = carrier_plate_len(carrier_dims_layout);
plate_wid = carrier_plate_wid(carrier_dims_layout);
stack_mount_positions_resolved = carrier_stack_mount_positions(carrier_dims_layout);

level_height = z_gap_clear + plate_thickness_cfg;
stack_height = (levels - 1) * level_height + plate_thickness_cfg;

// pi_stack_post currently wraps its geometry in rotate([0,0,45]) for internal math.
// Cancel that *at the call site* so the assembled stack stays in the carrier frame.
// This is a pure transform of imported geometry (no new geometry).
_post_cancel_z_rot = -45;

module _carrier(level = 0) {
    translate([-plate_len / 2, -plate_wid / 2, level * level_height])
        let(stack_bolt_d = stack_bolt_d_cfg)
            _maybe_render(convexity = 10)
                pi_carrier(
                    include_stack_mounts = true,
                    plate_thickness = plate_thickness_cfg,
                    stack_edge_margin = stack_edge_margin_cfg,
                    edge_margin = edge_margin_cfg,
                    stack_pocket_d = stack_pocket_d_cfg,
                    stack_pocket_depth = stack_pocket_depth_cfg,
                    emit_geometry_report = emit_geometry_report
                );
}

module _post_core(mount_pos) {
    // Decide per-corner feature twist:
    // - same-sign corners (++, --): leave at 0°
    // - mixed-sign corners (+-, -+): apply mixed_corner_feature_twist_deg_cfg (default 180°)
    sx = (mount_pos[0] < plate_len / 2) ? -1 : 1;
    sy = (mount_pos[1] < plate_wid / 2) ? -1 : 1;
    post_feature_twist_deg = (sx != sy) ? mixed_corner_feature_twist_deg_cfg : 0;

    // Pure import + transform of pi_stack_post geometry.
    _maybe_render(convexity = 20)
        rotate([0, 0, _post_cancel_z_rot])
            pi_stack_post(
                carrier_dims = carrier_dims_layout,
                mount_pos = mount_pos,
                plate_len = plate_len,
                plate_wid = plate_wid,

                levels = levels,
                z_gap_clear = z_gap_clear,
                plate_thickness = plate_thickness_cfg,

                edge_margin = edge_margin_cfg,
                stack_edge_margin = stack_edge_margin_cfg,
                stack_pocket_d = stack_pocket_d_cfg,
                stack_pocket_depth = stack_pocket_depth_cfg,

                stack_bolt_d = stack_bolt_d_cfg,

                post_body_d = post_body_d_cfg,
                post_overhang = post_overhang_cfg,
                fit_clearance = post_fit_clearance_cfg,
                leadin_depth = post_leadin_depth_cfg,
                leadin_extra_clearance = post_leadin_extra_clearance_cfg,

                // per-instance feature orientation control
                feature_twist_deg = post_feature_twist_deg,

                // Never emit post report from the stack wrapper.
                emit_post_report = false
            );
}

module _post_at_mount(mount_pos) {
    // Place the post so its bolt axis lands on the carrier's stack-mount center.
    translate([
        -plate_len / 2 + mount_pos[0],
        -plate_wid / 2 + mount_pos[1],
        0
    ])
        _post_core(mount_pos);
}

module _posts() {
    assert(len(stack_mount_positions_resolved) == 4,
        "expected exactly 4 stack mount positions for 4 corner posts");
    for (p = stack_mount_positions_resolved)
        _post_at_mount(p);
}

module pi_carrier_stack_preview_only() {
    // Posts first (clamp the full stack).
    _posts();

    // Carriers per level.
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
        export_part = export_part_resolved,
        stack_bolt_d = stack_bolt_d_cfg
    );
}

// Export modes:
// - carrier_level: a single carrier plate with stack mounts enabled
// - post: a single post (export one STL; print 4 copies)
// - assembly: full preview (carriers + 4 posts)
if (export_part_resolved == export_part_carrier_level) {
    _carrier(0);
} else if (export_part_resolved == export_part_post) {
    // Export a single post at the bottom-left mount position.
    // Keep consistent with historical behavior: center near origin for slicing convenience.
    p0 = stack_mount_positions_resolved[0];
    translate([-p0[0], -p0[1], 0])
        _post_core(p0);
} else {
    pi_carrier_stack_preview_only();
}
