include <./pi_dimensions.scad>;

// Spacer post that clamps between carrier levels using the stack mount pockets.
stack_bolt_d = is_undef(stack_bolt_d) ? 3.4 : stack_bolt_d;
stack_pocket_d = is_undef(stack_pocket_d) ? 9 : stack_pocket_d;
stack_pocket_depth = is_undef(stack_pocket_depth) ? 1.2 : stack_pocket_depth;
z_gap_clear = is_undef(z_gap_clear) ? 32 : z_gap_clear;
plate_thickness = is_undef(plate_thickness) ? 2.0 : plate_thickness;
post_body_d = is_undef(post_body_d) ? stack_pocket_d + 4 : post_body_d;
boss_fit_clearance = is_undef(boss_fit_clearance) ? 0.2 : boss_fit_clearance;
foot_flange_d = is_undef(foot_flange_d) ? post_body_d + 4 : foot_flange_d;

post_body_h = z_gap_clear;
boss_d = stack_pocket_d - boss_fit_clearance;
boss_h = max(stack_pocket_depth - 0.1, 0.1);
post_h = post_body_h + boss_h * 2;

assert(boss_fit_clearance > 0, "boss_fit_clearance must be positive so bosses key into pockets");
assert(boss_fit_clearance < stack_pocket_d, "boss_fit_clearance must be less than pocket diameter");
// Target ~0.2–0.4 mm clearance between the post boss and the locating pocket.
origin_center = post_body_h / 2;
echo(str("pi_stack_post: boss clearance = stack_pocket_d (", stack_pocket_d, ") - boss_d (", boss_d, ")"));

module _boss(z_offset = 0) {
    translate([0, 0, z_offset])
        cylinder(h = boss_h, r = boss_d / 2, $fn = 60);
}

module pi_stack_post(
    stack_bolt_d = stack_bolt_d,
    stack_pocket_d = stack_pocket_d,
    stack_pocket_depth = stack_pocket_depth,
    z_gap_clear = z_gap_clear,
    plate_thickness = plate_thickness,
    post_body_d = post_body_d,
    boss_fit_clearance = boss_fit_clearance,
    foot_flange_d = foot_flange_d
) {
    difference() {
        union() {
            translate([0, 0, -origin_center])
                cylinder(h = post_body_h, r = post_body_d / 2, $fn = 80);
            _boss(-origin_center - boss_h);
            _boss(origin_center);
            translate([0, 0, -origin_center - boss_h])
                cylinder(h = boss_h + min(1.5, boss_h), r = foot_flange_d / 2, $fn = 70);
        }

        translate([0, 0, -origin_center - boss_h - 0.01])
            cylinder(h = post_h + 0.02, r = stack_bolt_d / 2, $fn = 50);
    }
}

pi_stack_post();
