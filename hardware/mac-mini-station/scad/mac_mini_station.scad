// Mac mini M4 station with Magic Keyboard tray

// keyboard width presets
// keyboard_width_mm = 418.7; // full
keyboard_width_mm = 279;      // tenkeyless

keyboard_depth_mm = 114.9;
keyboard_front_height_mm = 4.1;
keyboard_back_height_mm = 10.9;

keyboard_incline_degrees = 3.387;
keyboard_full_stand_degrees = 40;
keyboard_incline_height_diff = keyboard_back_height_mm - keyboard_front_height_mm;

subtraction_padding_mm = 4;
subtraction_z_offset = keyboard_incline_height_diff + 1.4;
subtraction_x_offset = 0.5;
subtraction_vertical_padding = 2;

corner_radius = 9;
cylinder_height = keyboard_back_height_mm + 0.1;

mac_mini_m4_corner_radius = 18;
mac_mini_side_grille_gap = 4;
mac_mini_height = 43.5;
mac_mini_platform_wall_width = 5;
mac_mini_height_full = 50;
mac_mini_depth = 127;
mac_mini_saddle_wall_width = 2;

keyboard_middle_offset =
    keyboard_width_mm / 2 - mac_mini_height / 2 - mac_mini_platform_wall_width * 2;

PRINT_MAIN_STATION = true;
PRINT_SADDLE_CAP = true;
include <modules/saddle_cap_extension.scad>;

module keyboard_body_with_rounding() {
    hull() {
        translate([corner_radius, corner_radius, 0])
            cylinder(h = cylinder_height, r = corner_radius);
        translate([keyboard_width_mm - corner_radius, corner_radius, 0])
            cylinder(h = cylinder_height, r = corner_radius);
        translate([corner_radius, keyboard_depth_mm - corner_radius, 0])
            cylinder(h = cylinder_height, r = corner_radius);
        translate([keyboard_width_mm - corner_radius, keyboard_depth_mm - corner_radius, 0])
            cylinder(h = cylinder_height, r = corner_radius);
    }
}

module inclined_cutout() {
    translate([-subtraction_x_offset, 0, subtraction_z_offset * 0.5])
        rotate([keyboard_incline_degrees, 0, 0])
        cube([
            keyboard_width_mm + subtraction_padding_mm,
            keyboard_depth_mm + subtraction_padding_mm,
            keyboard_back_height_mm + subtraction_vertical_padding
        ]);
}

module mac_mini_m4_platform() {
    translate([keyboard_middle_offset, 0, 0])
        cube([
            mac_mini_height + mac_mini_platform_wall_width * 2,
            keyboard_depth_mm,
            keyboard_back_height_mm
        ]);
    translate([keyboard_middle_offset, 0, keyboard_back_height_mm])
        cube([mac_mini_platform_wall_width, keyboard_depth_mm, mac_mini_side_grille_gap]);
    translate([
        keyboard_width_mm / 2 + mac_mini_height / 2 - mac_mini_platform_wall_width,
        0,
        keyboard_back_height_mm
    ])
        cube([mac_mini_platform_wall_width, keyboard_depth_mm, mac_mini_side_grille_gap]);
    translate([
        keyboard_width_mm / 2 - mac_mini_height / 2 - mac_mini_platform_wall_width,
        0,
        keyboard_back_height_mm
    ])
        cube([mac_mini_height, mac_mini_platform_wall_width, mac_mini_side_grille_gap]);
    translate([
        keyboard_width_mm / 2 - mac_mini_height / 2 - mac_mini_platform_wall_width,
        keyboard_depth_mm - mac_mini_platform_wall_width,
        keyboard_back_height_mm
    ])
        cube([mac_mini_height, mac_mini_platform_wall_width, mac_mini_side_grille_gap]);
}

module mac_mini_m4_top_saddle() {
    difference() {
        translate([keyboard_middle_offset - 6, 0, 100])
            cube([
                mac_mini_height_full + mac_mini_saddle_wall_width * 2 + 0.4 + 10,
                mac_mini_depth + 0.4 + 10,
                60
            ]);
        translate([keyboard_middle_offset, 5, 80])
            cube([
                mac_mini_height_full + mac_mini_saddle_wall_width * 2 + 0.4,
                mac_mini_depth + 0.4,
                75
            ]);
        translate([keyboard_middle_offset + 22.2 - 2.5, -40, 75]) cube([20, 50, 100]);
        translate([
            keyboard_middle_offset + 36.3 - 12,
            keyboard_depth_mm + mac_mini_platform_wall_width + 10,
            95
        ])
            cube([12, 12, 60]);
    }
}

module keyboard_full_tray() {
    difference() {
        translate([keyboard_middle_offset + 1, 118, 159])
            rotate([90 + keyboard_full_stand_degrees, 0, 0])
            cube([50, keyboard_depth_mm, 100]);
        translate([keyboard_middle_offset - 3, -100, 50])
            cube([55, keyboard_depth_mm, 200]);
        translate([keyboard_middle_offset - 3, 0, 50])
            cube([55, keyboard_depth_mm, 110]);
    }
    translate([keyboard_middle_offset - 50, 114, 156])
        rotate([keyboard_full_stand_degrees, 0, 0]) cube([150, 5, 45]);
    translate([keyboard_middle_offset + 1, 120.15, 156])
        rotate([keyboard_full_stand_degrees, 0, 0]) cube([50, 5, 5]);
}

if (PRINT_MAIN_STATION) {
    difference() {
        keyboard_body_with_rounding();
        inclined_cutout();
    }
    mac_mini_m4_platform();
    mac_mini_m4_top_saddle();
    keyboard_full_tray();
}

if (PRINT_SADDLE_CAP) {
    saddle_cap_tray_extension();
}
