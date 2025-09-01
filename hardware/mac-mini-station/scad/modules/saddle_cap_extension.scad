// ------------------------------
// Saddle-cap tray extension (press-fit add-on)
// ------------------------------

// --- User-tunable parameters ---
press_fit_clearance_mm      = 0.35; // per side; adjust for printer tolerance
cap_wall_mm                 = 2.4;  // side walls thickness
cap_grip_height_mm          = 16;   // how far cap slides down over saddle
cap_top_plate_thickness_mm  = 3;    // thickness of plate under keyboard
wing_depth_mm               = min(keyboard_depth_mm, mac_mini_depth + 10);
wing_extra_each_side_mm     = max(
    40,
    (keyboard_width_mm - (mac_mini_height_full + mac_mini_saddle_wall_width * 2)) / 2 - 6
);
curb_height_mm              = 1.0;  // low side curb height
curb_thickness_mm           = 1.2;  // low side curb thickness

// --- Helper functions for existing saddle bbox ---
function saddle_outer_pos() = [keyboard_middle_offset - 6, 0, 100];
function saddle_outer_size() = [
    mac_mini_height_full + mac_mini_saddle_wall_width * 2 + 0.4 + 10,
    mac_mini_depth + 0.4 + 10,
    60
];

module saddle_cap_tray_extension() {
    S = saddle_outer_size();
    O = saddle_outer_pos();
    cap_top_z = O[2] + S[2];

    // 1) press-fit cap shell
    difference() {
        translate([
            O[0] - cap_wall_mm,
            O[1] - cap_wall_mm,
            cap_top_z - cap_grip_height_mm - cap_top_plate_thickness_mm
        ])
            cube([
                S[0] + 2 * cap_wall_mm,
                S[1] + 2 * cap_wall_mm,
                cap_grip_height_mm + cap_top_plate_thickness_mm
            ]);

        translate([
            O[0] - press_fit_clearance_mm,
            O[1] - press_fit_clearance_mm,
            cap_top_z - cap_grip_height_mm - 0.2
        ])
            cube([
                S[0] + 2 * press_fit_clearance_mm,
                S[1] + 2 * press_fit_clearance_mm,
                cap_grip_height_mm + 0.4
            ]);
    }

    // 2) left and right wings to widen support
    wing_y_start = O[1] + (S[1] - wing_depth_mm) / 2;

    translate([O[0] - wing_extra_each_side_mm, wing_y_start, cap_top_z])
        cube([wing_extra_each_side_mm, wing_depth_mm, cap_top_plate_thickness_mm]);
    translate([O[0] + S[0], wing_y_start, cap_top_z])
        cube([wing_extra_each_side_mm, wing_depth_mm, cap_top_plate_thickness_mm]);

    // 3) optional curbs at far edges
    if (curb_height_mm > 0) {
        translate([O[0] - wing_extra_each_side_mm, wing_y_start, cap_top_z])
            cube([curb_thickness_mm, wing_depth_mm, curb_height_mm]);
        translate([
            O[0] + S[0] + wing_extra_each_side_mm - curb_thickness_mm,
            wing_y_start,
            cap_top_z
        ])
            cube([curb_thickness_mm, wing_depth_mm, curb_height_mm]);
    }
}
