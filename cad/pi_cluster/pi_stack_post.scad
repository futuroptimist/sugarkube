// Full-height corner post for the stacked Pi carrier.
//
// Intent:
// - 4 posts total (one per carrier corner stack-mount).
// - A long bolt passes through the post and the carrier stack-mount holes,
//   clamping all carrier levels together.
// - The post is "keyed" to the carriers by subtracting slot cutouts derived from carrier plate
//   dimensions at each level (fast rectangular profile by default). A tighter carrier outline can
//   be reintroduced later if needed.
//
// PERFORMANCE NOTES (fast path):
// - Slot cutouts are rectangular prisms derived from carrier plate_len/plate_wid.
// - We do NOT add extra intersections around the subtractors by default.
//   In a difference(), OpenSCAD already only cares about subtractor volume that intersects the post.
//   Adding bounding intersections increases CSG complexity and can tank preview FPS.
// - Cylinder tessellation is reduced by default (low $fn).
//
// QUALITY / TUNING:
// - Default is optimized for *interactive preview*.
// - For printing, set `post_quality="print"` (or increase `post_fn`).
//
// CLI examples:
//   openscad -o /tmp/post_preview.stl cad/pi_cluster/pi_stack_post.scad -D post_quality="draft"
//   openscad -o /tmp/post_print.stl   cad/pi_cluster/pi_stack_post.scad -D post_quality="print"
//   openscad -o /tmp/post_print.stl   cad/pi_cluster/pi_stack_post.scad -D post_fn=48
//
// Z-FIGHTING FIX:
// - All subtractors overshoot slightly in Z (z_fudge) so boolean faces are not coplanar with the
//   post’s top/bottom faces. This removes the top-face flicker/wedge in preview.
//
// Coordinate system:
// - The post module is authored in a LOCAL coordinate system where the bolt axis is at XY=[0,0].
// - The carrier plate’s coordinate system is [0..plate_len]×[0..plate_wid] with the same origin
//   used by pi_carrier.scad.
// - Internally, we translate the plate region by -mount_pos so the chosen stack-mount center lands
//   on the bolt axis origin.
// - In pi_carrier_stack.scad, each post is placed by translating to the global stack-mount XY.

_pi_carrier_auto_render = false;
include <./pi_carrier.scad>; // imports carrier_dimensions() helpers

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
    // Plate region in local coordinates (after translating carrier by -mount_pos).
    // Expand by fit_clearance so prints don’t bind.
    x0 = -mount_pos[0] - fit_clearance;
    y0 = -mount_pos[1] - fit_clearance;
    sx = plate_len + 2 * fit_clearance;
    sy = plate_wid + 2 * fit_clearance;

    // Main slot (overshoot in Z to avoid coplanar faces)
    translate([x0, y0, z_plate - z_fudge])
        cube([sx, sy, plate_thickness + 2 * z_fudge], center = false);

    // Lead-in relief: slightly larger clearance near the bottom/top faces of each slot.
    if (leadin_depth > 0 && leadin_extra_clearance > 0) {
        lead = min(leadin_depth, plate_thickness);

        x1 = -mount_pos[0] - (fit_clearance + leadin_extra_clearance);
        y1 = -mount_pos[1] - (fit_clearance + leadin_extra_clearance);
        sx1 = plate_len + 2 * (fit_clearance + leadin_extra_clearance);
        sy1 = plate_wid + 2 * (fit_clearance + leadin_extra_clearance);

        // Bottom lead-in: extend slightly below the plate slot start
        translate([x1, y1, z_plate - z_fudge])
            cube([sx1, sy1, lead + z_fudge], center = false);

        // Top lead-in: extend slightly above the plate slot end
        translate([x1, y1, z_plate + plate_thickness - lead])
            cube([sx1, sy1, lead + z_fudge], center = false);
    }
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

    // Nut trap (bottom)
    include_nut_trap = is_undef(include_nut_trap) ? true : include_nut_trap,
    nut_flat = is_undef(nut_flat) ? 5.5 : nut_flat,        // M3 nut across flats (nominal)
    nut_thick = is_undef(nut_thick) ? 2.4 : nut_thick,
    nut_clearance = is_undef(nut_clearance) ? 0.5 : nut_clearance,
    nut_trap_extra = is_undef(nut_trap_extra) ? 0.3 : nut_trap_extra,

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
    // Avoid warnings from referencing unknown globals:
    // OpenSCAD warns if you pass an *unknown* variable into a function call.
    post_quality_cli = is_undef(post_quality) ? undef : post_quality;
    post_fn_cli = is_undef(post_fn) ? undef : post_fn;

    // Resolve quality from (module param) -> (CLI global) -> default.
    quality_resolved = _resolve_quality(quality, post_quality_cli, "draft");

    // Resolve facet count from (module param) -> (CLI global) -> derived from quality.
    fn_resolved = _resolve_fn(facet_fn, post_fn_cli, quality_resolved);

    // Anti-z-fighting / robust booleans (small, non-functional).
    z_fudge = 0.08;

    // Resolve carrier dims if not provided.
    // NOTE: Avoid direct reads of possibly-undefined vars.
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

    // If mount_pos isn't provided, default to the first (bottom-left) stack mount.
    mounts = carrier_stack_mount_positions(carrier_dims_resolved);
    mount_pos_resolved =
        is_undef(mount_pos)
            ? (len(mounts) > 0 ? mounts[0] : [0, 0])
            : mount_pos;

    // Determine which corner this mount corresponds to (for outward offset).
    sx = (mount_pos_resolved[0] < plate_len_resolved / 2) ? -1 : 1;
    sy = (mount_pos_resolved[1] < plate_wid_resolved / 2) ? -1 : 1;

    edge_dx = min(mount_pos_resolved[0], plate_len_resolved - mount_pos_resolved[0]);
    edge_dy = min(mount_pos_resolved[1], plate_wid_resolved - mount_pos_resolved[1]);

    post_r = post_body_d / 2;
    bolt_r = stack_bolt_d / 2;

    // Position the post cylinder so it extends outward past the plate edges by post_overhang,
    // while keeping ≥post_wall_min around the bolt.
    post_center_raw = [
        sx * (edge_dx + post_overhang - post_r),
        sy * (edge_dy + post_overhang - post_r)
    ];

    // Clamp offset to preserve wall around bolt (prevents impossible offsets).
    wall_eps = 0.03;
    allowed_center_dist = post_r - bolt_r - post_wall_min - wall_eps;
    assert(allowed_center_dist > 0,
        "post_body_d too small to preserve post_wall_min around bolt; increase post_body_d or reduce post_wall_min or stack_bolt_d");

    center_dist_raw =
        sqrt(post_center_raw[0]*post_center_raw[0] + post_center_raw[1]*post_center_raw[1]);

    center_scale =
        (center_dist_raw > allowed_center_dist && center_dist_raw > 0)
            ? (allowed_center_dist / center_dist_raw)
            : 1;

    post_center = [
        post_center_raw[0] * center_scale,
        post_center_raw[1] * center_scale
    ];

    level_height = z_gap_clear + plate_thickness;
    stack_height = (levels - 1) * level_height + plate_thickness;

    nut_trap_depth = nut_thick + nut_trap_extra;
    bottom_extra_resolved =
        is_undef(bottom_extra)
            ? (include_nut_trap ? max(nut_trap_depth + 0.8, 3.0) : 1.0)
            : bottom_extra;

    post_h = stack_height + bottom_extra_resolved + top_extra;
    z_post0 = -bottom_extra_resolved;

    // Minimum radial wall at the bolt axis, considering the clamped post offset.
    center_dist = sqrt(post_center[0]*post_center[0] + post_center[1]*post_center[1]);
    min_radial_wall = (post_r - center_dist) - bolt_r;

    // Guards
    assert(fit_clearance > 0, "fit_clearance must be > 0 to avoid binding on real prints");
    assert(post_body_d > stack_bolt_d + 2 * post_wall_min, "post_body_d too small for stack_bolt_d + post_wall_min");
    tolerance_eps = 0.001;
    assert(min_radial_wall + tolerance_eps >= post_wall_min,
        str("post too offset even after clamping: need ≥", post_wall_min,
            "mm wall around bolt; have ", min_radial_wall,
            "mm. Increase post_body_d or reduce post_overhang."));
    assert(leadin_depth >= 0, "leadin_depth must be non-negative");
    assert(2 * stack_pocket_depth < plate_thickness,
        "stack_pocket_depth must be < half of plate_thickness so symmetric pockets do not overlap");

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
            slot_profile = slot_profile,
            quality = quality_resolved,
            fn = fn_resolved,
            bottom_extra = bottom_extra_resolved,
            top_extra = top_extra
        );
    }

    // Apply tessellation to cylinders only; cubes are already "free".
    let($fn = fn_resolved)
    difference() {
        // --- Solid post body ---
        translate([post_center[0], post_center[1], z_post0])
            cylinder(h = post_h, r = post_r);

        // --- Subtractors as a single union (keeps CSG flatter in preview) ---
        union() {
            // Bolt clearance bore (overshoot in Z avoids coplanar faces)
            translate([0, 0, z_post0 - 0.3])
                cylinder(h = post_h + 0.6, r = bolt_r);

            // Bottom nut trap (optional)
            if (include_nut_trap) {
                nut_flat_eff = nut_flat + nut_clearance;
                nut_r = nut_flat_eff / (2 * cos(30));
                translate([0, 0, z_post0 - 0.15])
                    cylinder(h = nut_trap_depth + 0.3, r = nut_r, $fn = 6);
            }

            // Plate slots at each level
            for (lvl = [0 : levels - 1]) {
                z_plate = lvl * level_height;

                // Fast default: rectangular plate region (uses plate_len/plate_wid from carrier_dimensions).
                if (slot_profile == "rect") {
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
                } else {
                    // Fallback: treat unknown profiles as rect to stay fast/stable.
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
                }
            }
        }
    }
}

// Standalone preview: render a single post (defaults to the first stack mount).
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

    // Defaults:
    // - post_quality="draft" → low $fn for fast preview
    // For printing:
    // -D post_quality="print"   (or -D post_fn=48)
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
        include_nut_trap = true,
        slot_profile = "rect",
        emit_post_report = true
    );
}
