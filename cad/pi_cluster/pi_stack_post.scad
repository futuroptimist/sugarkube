include <./pi_carrier.scad>;

stack_bolt_d = is_undef(stack_bolt_d) ? 3.4 : stack_bolt_d;
stack_pocket_d = is_undef(stack_pocket_d) ? 8 : stack_pocket_d;
stack_pocket_depth = is_undef(stack_pocket_depth) ? 1.6 : stack_pocket_depth;
post_od = is_undef(post_od) ? 14 : post_od;
z_gap_clear = is_undef(z_gap_clear) ? 32 : z_gap_clear;
post_chamfer = is_undef(post_chamfer) ? 0.8 : post_chamfer;
foot_height = is_undef(foot_height) ? 1.2 : foot_height;

post_height = z_gap_clear;
body_height = post_height - stack_pocket_depth;

module _stack_post_body() {
    cylinder(h = body_height, r = post_od / 2, $fn = 90);
    translate([0, 0, body_height - post_chamfer])
        cylinder(h = post_chamfer, r1 = post_od / 2, r2 = post_od / 2 - post_chamfer, $fn = 60);
}

module _stack_post_core() {
    translate([0, 0, -0.2])
        cylinder(h = post_height + 0.4, r = stack_bolt_d / 2, $fn = 50);
}

module stack_post() {
    translate([0, 0, stack_pocket_depth])
        _stack_post_body();

    translate([0, 0, 0])
        cylinder(h = stack_pocket_depth + foot_height, r = stack_pocket_d / 2, $fn = 80);

    _stack_post_core();
}

stack_post();
