// Full-height corner post for the stacked Pi carrier.
//
// Intent:
// - 4 posts total (one per carrier corner stack-mount).
// - A long bolt passes through the post and the carrier stack-mount holes,
//   clamping all carrier levels together.
// - The post is keyed to the carriers by subtracting slot cutouts derived from carrier plate
//   dimensions at each level (fast rectangular profile by default).
//
// Printing goal:
// - Make the bottom slot ceilings printable on FDM without supports by cutting 45° “roof” ramps.
//
// Performance notes:
// - Slot cutouts are simple rectangular prisms (fast).
// - Cylinder tessellation is reduced by default (low $fn).
//
// Z-fighting fix:
// - Subtractors overshoot slightly in Z (z_fudge) to avoid coplanar faces.
//
// Coordinate system:
// - Local: bolt axis at XY=[0,0].
// - Carrier plate coords: [0..plate_len]×[0..plate_wid] (same origin as pi_carrier.scad).
// - We translate plate region by -mount_pos so stack-mount center lands on the bolt axis.
// - In pi_carrier_stack.scad, each post is placed by translating to the global stack-mount XY.
//
// Geometry invariance harness:
// - Validate refactors with:
//   openscad -o /tmp/ignore.stl cad/pi_cluster/pi_stack_post.scad -D emit_post_report=true > /tmp/post_report.before.txt 2>&1
//   openscad -o /tmp/ignore.stl cad/pi_cluster/pi_stack_post.scad -D emit_post_report=true > /tmp/post_report.after.txt 2>&1
//   diff -u /tmp/post_report.before.txt /tmp/post_report.after.txt
//   The echoed pi_stack_post values must be identical (geometry-preserving refactor).

// Note:
// - This module applies rotate([0,0,45]) around the origin to simplify wedge math during development.
//   The geometry is preserved exactly as currently dialed in.

_pi_carrier_auto_render = false;
include <./pi_carrier.scad>; // imports carrier_dimensions() helpers

// Keep stack part selectors defined so CLI overrides like -D export_part=carrier_level resolve
// to a string literal even when only this file is rendered.
carrier_level = "carrier_level";
post = "post";
assembly = "assembly";

// ============================================================================
// ---- Wedge tuning parameters (dialed-in; do not change without re-tuning) ----
// WEDGE_TUNE_KNOBS
wedge_tune_world_y_mm = 12.274;   // mm (world Y, applied after rotate([0,0,45]))
wedge_tune_world_z_mm = 0.15;     // mm (world Z)
wedge_tune_scale = 2.5;           // unitless (isotropic scale about wedge origin)

// DEBUG_TETRA: comment/uncomment THIS ONE LINE to toggle BOTH tetra debug previews.
// debug_show_tetra = true;
debug_show_tetra = false;

// ---- Micro-tetra tuning knobs (anchor at RIGHT-ANGLE vertex) ----
// TETRA_TUNE_KNOBS
micro_tet_anchor_scale = 7.0;     // unitless (isotropic)
micro_tet_tune_y_mm = -47.82;     // mm (WORLD Y tuning)
micro_tet_tune_z_mm = 3.08;       // mm (WORLD Z tuning)

// ---- Micro-ceiling tetrahedron shaver (other constants) ----
micro_tet_leg_mm   = 6.0;         // mm
micro_tet_tune_x_mm = 0.0;        // mm (reserved)
micro_tet_inset_mm  = 0.8;        // mm (reserved)
micro_tet_base_z_mm = 0.12;       // mm (reserved)
// ============================================================================


// ---------- Quality controls ----------
function _quality_fn(q) =
    q == "high"        ? 96 :
    q == "print"       ? 48 :
    q == "draft"       ? 20 :
    q == "ultra_draft" ? 12 :
    20;

function _resolve_quality(quality_param, post_quality_cli, fallback = "draft") =
    !is_undef(quality_param) ? quality_param
    : (!is_undef(post_quality_cli) ? post_quality_cli : fallback);

function _resolve_fn(facet_fn_param, post_fn_cli, quality_resolved) =
    !is_undef(facet_fn_param) ? facet_fn_param
    : (!is_undef(post_fn_cli) ? post_fn_cli : _quality_fn(quality_resolved));


// ---------- Helpers ----------
module _slot_cutout_rect(
    plate_len,
    plate_wid,
    mount_pos,
    z_plate,
    plate_thickness,
    fit_clearance,
    leadin_depth,
    leadin_extra_clearance,
    z_fudge
) {
    x0 = -mount_pos[0] - fit_clearance;
    y0 = -mount_pos[1] - fit_clearance;
    sx = plate_len + 2 * fit_clearance;
    sy = plate_wid + 2 * fit_clearance;

    // Main slot
    translate([x0, y0, z_plate - z_fudge])
        cube([sx, sy, plate_thickness + 2 * z_fudge], center = false);

    // Lead-in relief
    //
    // IMPORTANT (printability):
    // The bottom lead-in creates an internal horizontal ceiling (a tiny “spacer”)
    // that can still want supports / string. In this supportless-print tuning we
    // deliberately remove the bottom lead-in and keep only the TOP lead-in.
    if (leadin_depth > 0 && leadin_extra_clearance > 0) {
        lead = min(leadin_depth, plate_thickness);

        x1 = -mount_pos[0] - (fit_clearance + leadin_extra_clearance);
        y1 = -mount_pos[1] - (fit_clearance + leadin_extra_clearance);
        sx1 = plate_len + 2 * (fit_clearance + leadin_extra_clearance);
        sy1 = plate_wid + 2 * (fit_clearance + leadin_extra_clearance);

        // Top lead-in: extend slightly above the plate slot end
        translate([x1, y1, z_plate + plate_thickness - lead])
            cube([sx1, sy1, lead + z_fudge], center = false);

        // NOTE: Bottom lead-in intentionally omitted.
    }
}

// 45° roof wedge: triangular prism used as a subtractor above the slot roof.
function _world_y_to_local_xy_offset(y_mm) = y_mm / sqrt(2);

// Goal: produce a 45° roof plane facing into the slot cavity; keep the wedge
// anchored at the outer slot corner; flips ensure the ramp slopes downward into
// the cavity after the global 45° alignment.
module _wedge_orient_for_slot(theta) {
    // WORLD Z flip (commutes with the outer rotate([0,0,45])).
    rotate([0, 0, 180])
        // WORLD X flip expressed in local coords under the 45° wrapper.
        rotate([0, 0, -45])
            rotate([180, 0, 0])
                rotate([0, 0, 45])
                    // Slot-corner alignment around WORLD/slot Z.
                    rotate([0, 0, theta])
                        // Triangle plane mapped to the XY plane for extrusion.
                        rotate([-90, 0, 0])
                            children();
}

module _simple_roof_wedge(
    plate_len,
    plate_wid,
    mount_pos,
    fit_clearance,
    corner_sign,     // [sx, sy] ∈ {±1, ±1}
    z_roof,
    wedge_h,
    wedge_width,
    z_fudge
) {
    sx_corner = corner_sign[0];
    sy_corner = corner_sign[1];

    x0 = -mount_pos[0] - fit_clearance;
    y0 = -mount_pos[1] - fit_clearance;
    dx = plate_len + 2 * fit_clearance;
    dy = plate_wid + 2 * fit_clearance;

    x_edge = (sx_corner < 0) ? x0 : (x0 + dx);
    y_edge = (sy_corner < 0) ? y0 : (y0 + dy);

    theta = atan2(sy_corner, sx_corner);

    world_y_to_local_xy_offset = _world_y_to_local_xy_offset(wedge_tune_world_y_mm);

    // WORLD +Z offset is unchanged by the outer Z rotation.
    world_z_offset = wedge_tune_world_z_mm;

    translate([x_edge + world_y_to_local_xy_offset, y_edge + world_y_to_local_xy_offset, (z_roof - z_fudge) + world_z_offset])
        // Scale after anchoring translate (keeps the anchor corner fixed while growing/shrinking).
        scale([wedge_tune_scale, wedge_tune_scale, wedge_tune_scale])
            _wedge_orient_for_slot(theta)
                linear_extrude(height = wedge_width, center = true)
                    polygon(points = [
                        [0, 0],
                        [-wedge_h, 0],
                        [-wedge_h, wedge_h]
                    ]);
}


// --- Micro-ceiling tetrahedron: 45° tetra (anchor at right-angle vertex) ---
// Anchor vertex A=(0,0,0). Scaling about origin keeps A fixed.
module _tetra_45_axis_anchorA(L) {
    pts = [
        [0,   0,   0],      // A (ANCHOR: right angle)
        [L,   0,   0],      // B
        [0,   L,   0],      // C
        [L/2, L/2, L/2]     // D
    ];
    fcs = [
        [0, 2, 1],  // base
        [0, 1, 3],
        [0, 3, 2],
        [1, 2, 3]
    ];
    polyhedron(points = pts, faces = fcs, convexity = 10);
}

// Subtractor placement for the tuned tetrahedron.
// Called INSIDE rotate([0,0,45]) wrapper.
// z_world_extra_mm clones the tetra upward by exactly one carrier level height.
module _micro_tetra_subtractor_worldanchored(z_world_extra_mm = 0) {
    // Anchor in WORLD coords (matched to the debug marker workflow).
    y_world = 30 + micro_tet_tune_y_mm;
    z_world = 0 + micro_tet_tune_z_mm + z_world_extra_mm;

    // Under the outer rotate([0,0,45]) wrapper:
    // world +Y corresponds to local [+off, +off].
    off = _world_y_to_local_xy_offset(y_world);

    translate([off, off, z_world])
        scale([micro_tet_anchor_scale, micro_tet_anchor_scale, micro_tet_anchor_scale])
            _tetra_45_axis_anchorA(micro_tet_leg_mm);
}


// ---------- Main module ----------
module pi_stack_post(
    // Required coupling inputs (provided by pi_carrier_stack.scad)
    mount_pos = undef,  // [x,y] in carrier plate coordinates (stack mount center)
    plate_len = undef,
    plate_wid = undef,

    // Stack sizing
    levels = is_undef(levels) ? 3 : levels,
    z_gap_clear = is_undef(z_gap_clear) ? 32 : z_gap_clear,
    plate_thickness = is_undef(plate_thickness) ? 3.0 : plate_thickness,

    // Carrier-derived geometry (recommended to pass in from the stack wrapper)
    carrier_dims = undef,
    edge_margin = is_undef(edge_margin) ? 15 : edge_margin,
    stack_edge_margin = is_undef(stack_edge_margin) ? 15 : stack_edge_margin,

    // Must match the carrier stack-mount pockets (used only for dimension derivation / debug)
    stack_pocket_d = is_undef(stack_pocket_d) ? 9 : stack_pocket_d,
    stack_pocket_depth = is_undef(stack_pocket_depth) ? 1.2 : stack_pocket_depth,

    // Bolt path
    stack_bolt_d = is_undef(stack_bolt_d) ? 3.4 : stack_bolt_d, // M3 clearance (print-friendly)

    // Post shape
    post_body_d = is_undef(post_body_d) ? 26 : post_body_d,
    post_overhang = is_undef(post_overhang) ? 5 : post_overhang,
    post_wall_min = is_undef(post_wall_min) ? 2.0 : post_wall_min,

    // Fit tuning
    fit_clearance = is_undef(fit_clearance) ? 0.2 : fit_clearance,
    leadin_depth = is_undef(leadin_depth) ? 0.8 : leadin_depth,
    leadin_extra_clearance = is_undef(leadin_extra_clearance) ? 0.4 : leadin_extra_clearance,

    // Wedge tuning (45° roof ramps)
    roof_wedge_h = is_undef(roof_wedge_h) ? 5 : roof_wedge_h,
    roof_wedge_width = is_undef(roof_wedge_width) ? 40 : roof_wedge_width,

    // Z extensions
    bottom_extra = is_undef(bottom_extra) ? undef : bottom_extra,
    top_extra = is_undef(top_extra) ? 0 : top_extra,

    // Geometry mode (kept for future expansion; "rect" is the fast path)
    slot_profile = is_undef(slot_profile) ? "rect" : slot_profile,

    // Tessellation / quality controls:
    // - module param `quality` overrides CLI `post_quality`
    // - module param `facet_fn` overrides CLI `post_fn`
    quality = undef,
    facet_fn = undef,

    // Debug
    emit_post_report = is_undef(emit_post_report) ? false : emit_post_report
) {
    post_quality_cli = is_undef(post_quality) ? undef : post_quality;
    post_fn_cli = is_undef(post_fn) ? undef : post_fn;

    quality_resolved = _resolve_quality(quality, post_quality_cli, "draft");
    fn_resolved = _resolve_fn(facet_fn, post_fn_cli, quality_resolved);

    // Robust booleans (small, non-functional).
    z_fudge = 0.08;

    // Resolve carrier dims if not provided.
    stack_mount_positions_input_safe =
        is_undef(stack_mount_positions) ? undef : stack_mount_positions;

    carrier_dims_resolved = is_undef(carrier_dims)
        ? carrier_dimensions(
            include_stack_mounts = true,
            stack_edge_margin = stack_edge_margin,
            edge_margin = edge_margin,
            plate_thickness = plate_thickness,
            stack_pocket_depth = stack_pocket_depth,
            stack_pocket_d = stack_pocket_d,
            stack_mount_positions_input = stack_mount_positions_input_safe
        )
        : carrier_dims;

    plate_len_resolved = is_undef(plate_len) ? carrier_plate_len(carrier_dims_resolved) : plate_len;
    plate_wid_resolved = is_undef(plate_wid) ? carrier_plate_wid(carrier_dims_resolved) : plate_wid;

    mounts = carrier_stack_mount_positions(carrier_dims_resolved);
    mount_pos_resolved =
        is_undef(mount_pos)
            ? (len(mounts) > 0 ? mounts[0] : [0, 0])
            : mount_pos;

    // Determine which corner this mount corresponds to.
    sx = (mount_pos_resolved[0] < plate_len_resolved / 2) ? -1 : 1;
    sy = (mount_pos_resolved[1] < plate_wid_resolved / 2) ? -1 : 1;

    edge_dx = min(mount_pos_resolved[0], plate_len_resolved - mount_pos_resolved[0]);
    edge_dy = min(mount_pos_resolved[1], plate_wid_resolved - mount_pos_resolved[1]);

    post_r = post_body_d / 2;
    bolt_r = stack_bolt_d / 2;

    // Position the post cylinder to extend outward past plate edges by post_overhang,
    // while keeping >=post_wall_min around the bolt.
    post_center_raw = [
        sx * (edge_dx + post_overhang - post_r),
        sy * (edge_dy + post_overhang - post_r)
    ];

    // Clamp offset to preserve wall around bolt.
    wall_eps = 0.03;
    allowed_center_dist = post_r - bolt_r - post_wall_min - wall_eps;

    center_dist_raw =
        sqrt(post_center_raw[0]*post_center_raw[0] + post_center_raw[1]*post_center_raw[1]);

    center_scale =
        (allowed_center_dist > 0 && center_dist_raw > allowed_center_dist && center_dist_raw > 0)
            ? (allowed_center_dist / center_dist_raw)
            : 1;

    post_center = [
        post_center_raw[0] * center_scale,
        post_center_raw[1] * center_scale
    ];

    level_height = z_gap_clear + plate_thickness;
    stack_height = (levels - 1) * level_height + plate_thickness;

    default_bottom_extra = 3.1;
    bottom_extra_resolved =
        is_undef(bottom_extra) ? default_bottom_extra : bottom_extra;

    post_h = stack_height + bottom_extra_resolved + top_extra;
    z_post0 = -bottom_extra_resolved;

    center_dist = sqrt(post_center[0]*post_center[0] + post_center[1]*post_center[1]);
    min_radial_wall = (post_r - center_dist) - bolt_r;

    // Always emit a lightweight line whenever this module is instantiated/generated.
    echo(
        "pi_stack_post_generated",
        mount_pos = mount_pos_resolved,
        corner_sign = [sx, sy],
        levels = levels,
        z_gap_clear = z_gap_clear,
        plate_thickness = plate_thickness,
        level_height = level_height,
        post_center = post_center,
        stack_bolt_d = stack_bolt_d,
        post_body_d = post_body_d,
        debug_show_tetra = debug_show_tetra
    );

    // Guards
    assert(allowed_center_dist > 0,
        "post_body_d too small to preserve post_wall_min around bolt; increase post_body_d or reduce post_wall_min or stack_bolt_d");
    assert(fit_clearance > 0, "fit_clearance must be > 0 to avoid binding on real prints");
    assert(post_body_d > stack_bolt_d + 2 * post_wall_min, "post_body_d too small for stack_bolt_d + post_wall_min");
    tolerance_eps = 0.001;
    assert(min_radial_wall + tolerance_eps >= post_wall_min,
        str("post too offset even after clamping: need ≥", post_wall_min,
            "mm wall around bolt; have ", min_radial_wall,
            "mm. Increase post_body_d or reduce post_overhang."));
    assert(leadin_depth >= 0, "leadin_depth must be non-negative");
    assert(roof_wedge_h >= 0, "roof_wedge_h must be non-negative");
    assert(roof_wedge_width > 0, "roof_wedge_width must be > 0");
    assert(2 * stack_pocket_depth < plate_thickness,
        "stack_pocket_depth must be < half of plate_thickness so symmetric pockets do not overlap");

    // Keep the existing detailed report behind the flag.
    if (emit_post_report) {
        echo(
            "pi_stack_post",
            mount_pos = mount_pos_resolved,
            corner_sign = [sx, sy],
            plate_len = plate_len_resolved,
            plate_wid = plate_wid_resolved,
            levels = levels,
            z_gap_clear = z_gap_clear,
            plate_thickness = plate_thickness,
            stack_height = stack_height,
            post_body_d = post_body_d,
            post_overhang_requested = post_overhang,
            post_center = post_center,
            stack_bolt_d = stack_bolt_d,
            min_radial_wall = min_radial_wall,
            fit_clearance = fit_clearance,
            leadin_depth = leadin_depth,
            leadin_extra_clearance = leadin_extra_clearance,
            roof_wedge_h = roof_wedge_h,
            roof_wedge_width = roof_wedge_width,
            slot_profile = slot_profile,
            quality = quality_resolved,
            fn = fn_resolved,
            bottom_extra = bottom_extra_resolved,
            top_extra = top_extra
        );
    }

    // DEBUG MARKERS (visual only; subtraction is always applied below)
    // When enabled, show BOTH tetrahedra (bottom + one-level-up) with # highlights.
    if (!is_undef(debug_show_tetra) && debug_show_tetra) {
        #translate([0, 30 + micro_tet_tune_y_mm, 0 + micro_tet_tune_z_mm])
            rotate([0, 0, 45])
                scale([micro_tet_anchor_scale, micro_tet_anchor_scale, micro_tet_anchor_scale])
                    _tetra_45_axis_anchorA(micro_tet_leg_mm);

        #translate([0, 30 + micro_tet_tune_y_mm, level_height + micro_tet_tune_z_mm])
            rotate([0, 0, 45])
                scale([micro_tet_anchor_scale, micro_tet_anchor_scale, micro_tet_anchor_scale])
                    _tetra_45_axis_anchorA(micro_tet_leg_mm);
    }

    // Apply +45° Z rotation around origin (kept as-is; geometry is already dialed in).
    rotate([0, 0, 45]) {

        // Apply tessellation to cylinders only; cubes are already "free".
        let($fn = fn_resolved)
        difference() {
            // --- Solid post body ---
            translate([post_center[0], post_center[1], z_post0])
                cylinder(h = post_h, r = post_r);

            // --- Subtractors as a single union ---
            union() {
                // Bolt clearance bore
                translate([0, 0, z_post0 - 0.3])
                    cylinder(h = post_h + 0.6, r = bolt_r);

                // Micro-ceiling tetra subtractors (ALWAYS ON):
                _micro_tetra_subtractor_worldanchored(0);
                _micro_tetra_subtractor_worldanchored(level_height);

                // Plate slots at each level
                for (lvl = [0 : levels - 1]) {
                    z_plate = lvl * level_height;

                    _slot_cutout_rect(
                        plate_len = plate_len_resolved,
                        plate_wid = plate_wid_resolved,
                        mount_pos = mount_pos_resolved,
                        z_plate = z_plate,
                        plate_thickness = plate_thickness,
                        fit_clearance = fit_clearance,
                        leadin_depth = leadin_depth,
                        leadin_extra_clearance = leadin_extra_clearance,
                        z_fudge = z_fudge
                    );

                    // Apply wedge to all slots except the top (top slot has no ceiling).
                    if (lvl < levels - 1) {
                        _simple_roof_wedge(
                            plate_len = plate_len_resolved,
                            plate_wid = plate_wid_resolved,
                            mount_pos = mount_pos_resolved,
                            fit_clearance = fit_clearance,
                            corner_sign = [sx, sy],
                            z_roof = z_plate + plate_thickness,
                            wedge_h = roof_wedge_h,
                            wedge_width = roof_wedge_width,
                            z_fudge = z_fudge
                        );
                    }
                }
            }
        }
    }
}

// Standalone render: a single post (defaults to the first stack mount).
if (is_undef(_pi_stack_post_auto_render) ? true : _pi_stack_post_auto_render) {
    _preview_plate_t = 3.0;
    _preview_levels = 3;
    _preview_z_gap = 32;

    _preview_stack_pocket_d = 9;
    _preview_stack_pocket_depth = min(1.2, _preview_plate_t / 2 - 0.1);

    _stack_mount_positions_input_safe =
        is_undef(stack_mount_positions) ? undef : stack_mount_positions;

    _dims = carrier_dimensions(
        include_stack_mounts = true,
        plate_thickness = _preview_plate_t,
        edge_margin = 15,
        stack_edge_margin = 15,
        stack_pocket_d = _preview_stack_pocket_d,
        stack_pocket_depth = _preview_stack_pocket_depth,
        stack_mount_positions_input = _stack_mount_positions_input_safe
    );

    _mounts = carrier_stack_mount_positions(_dims);

    pi_stack_post(
        carrier_dims = _dims,
        mount_pos = _mounts[0],
        plate_len = carrier_plate_len(_dims),
        plate_wid = carrier_plate_wid(_dims),
        levels = _preview_levels,
        z_gap_clear = _preview_z_gap,
        plate_thickness = _preview_plate_t,
        stack_pocket_d = _preview_stack_pocket_d,
        stack_pocket_depth = _preview_stack_pocket_depth,
        stack_bolt_d = 3.4,
        post_body_d = 26,
        post_overhang = 5,
        post_wall_min = 2.0,
        fit_clearance = 0.2,
        leadin_depth = 0.8,
        leadin_extra_clearance = 0.4,

        roof_wedge_h = 5,
        roof_wedge_width = 40,

        slot_profile = "rect",
        emit_post_report = true
    );
}
