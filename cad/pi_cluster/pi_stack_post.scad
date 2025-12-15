include <./pi_carrier.scad>;

stack_bolt_d = is_undef(stack_bolt_d) ? 3.4 : stack_bolt_d;
stack_pocket_d = is_undef(stack_pocket_d) ? 8.5 : stack_pocket_d;
stack_pocket_depth = is_undef(stack_pocket_depth) ? 1.0 : stack_pocket_depth;
z_gap_clear = is_undef(z_gap_clear) ? 32 : z_gap_clear;
plate_thickness = is_undef(plate_thickness) ? 2.0 : plate_thickness;
foot_flange = is_undef(foot_flange) ? 1.0 : foot_flange;
post_clearance = is_undef(post_clearance) ? 0.25 : post_clearance;

post_body_d = stack_pocket_d + 2 * post_clearance;
post_height = z_gap_clear;

module pi_stack_post() {
    difference() {
        union() {
            cylinder(h = post_height, r = post_body_d / 2, $fn = 80);
            translate([0, 0, -foot_flange])
                cylinder(h = foot_flange, r = post_body_d / 2 + 1.2, $fn = 70);
            cylinder(h = stack_pocket_depth + 0.2, r = stack_pocket_d / 2, $fn = 70);
        }

        translate([0, 0, -0.2])
            cylinder(h = post_height + 0.4, r = stack_bolt_d / 2, $fn = 60);
    }

    translate([0, 0, post_height - 0.8])
        cylinder(h = 0.8, r1 = post_body_d / 2 - 0.4, r2 = post_body_d / 2, $fn = 60);
}

pi_stack_post();
