// Spacer post for modular pi carrier stack assemblies.
include <./pi_dimensions.scad>;

z_gap_clear = is_undef(z_gap_clear) ? 32 : z_gap_clear;
stack_bolt_d = is_undef(stack_bolt_d) ? 3.4 : stack_bolt_d;
stack_pocket_d = is_undef(stack_pocket_d) ? 8 : stack_pocket_d;
stack_pocket_depth = is_undef(stack_pocket_depth) ? 0.6 : stack_pocket_depth;
plate_thickness = is_undef(plate_thickness) ? 2.0 : plate_thickness;
post_height = is_undef(post_height) ? z_gap_clear : post_height;
boss_height = is_undef(boss_height) ? stack_pocket_depth + 0.6 : boss_height;
post_diameter = is_undef(post_diameter) ? stack_pocket_d + 4 : post_diameter;
foot_diameter = is_undef(foot_diameter) ? stack_pocket_d + 6 : foot_diameter;
foot_thickness = is_undef(foot_thickness) ? 1.2 : foot_thickness;
chamfer_h = 0.6;

module pi_stack_post(
    z_gap_clear = z_gap_clear,
    stack_bolt_d = stack_bolt_d,
    stack_pocket_d = stack_pocket_d,
    stack_pocket_depth = stack_pocket_depth,
    plate_thickness = plate_thickness,
    post_height = post_height,
    boss_height = boss_height,
    post_diameter = post_diameter,
    foot_diameter = foot_diameter,
    foot_thickness = foot_thickness
) {
    body_height = post_height + foot_thickness;
    difference() {
        union() {
            // Stabilising foot
            translate([0, 0, -foot_thickness])
                cylinder(h = foot_thickness, r = foot_diameter / 2, $fn = 64);

            // Main spacer section (height equals z_gap_clear by default)
            cylinder(h = post_height, r = post_diameter / 2, $fn = 64);

            // Locating boss to seat into stack pockets
            translate([0, 0, -boss_height])
                cylinder(h = boss_height, r = stack_pocket_d / 2 - 0.2, $fn = 50);
        }

        // Through hole for tie-rod / bolt
        translate([0, 0, -boss_height - 0.1])
            cylinder(h = body_height + boss_height + 0.2, r = stack_bolt_d / 2, $fn = 40);
    }

    // Small lead-in at the top for easier plate alignment
    translate([0, 0, post_height - chamfer_h])
        cylinder(h = chamfer_h, r1 = post_diameter / 2 - 0.6, r2 = post_diameter / 2, $fn = 40);
}

pi_stack_post();
