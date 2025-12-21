// Helper functions for PC fan geometry shared across the stacked carrier modules.

// Toggle to render a simple preview when this file is opened directly.
// Downstream includes can set `_fan_patterns_auto_render = false;` to suppress it.
_fan_patterns_auto_render =
    is_undef(_fan_patterns_auto_render) ? true : _fan_patterns_auto_render;

fan_preview_size = is_undef(fan_preview_size) ? 120 : fan_preview_size;

function fan_hole_spacing(fan_size) =
    fan_size == 120 ? 105 :
    fan_size == 92  ? 82.5 :
    fan_size == 80  ? 71.5 :
    105;

function fan_mount_clearance(fan_size) = 3.4; // Through hole for M3 screws with margin.

function fan_hole_circle_d(fan_size) =
    4.5; // M4/#6 pass-through (oversize for M3 screws per stack doc guidance).

function fan_square_pattern(fan_size, spacing = undef) =
    let(
        spacing_resolved = is_undef(spacing) ? fan_hole_spacing(fan_size) : spacing,
        half = spacing_resolved / 2
    )
        [
            [-half, -half],
            [half, -half],
            [-half, half],
            [half, half],
        ];

function fan_face_extent(fan_size) = fan_size + 24; // Adds a 12 mm rim on each edge for stiffness.


module fan_pattern_preview(fan_size = fan_preview_size) {
    // Rim outline for visual context.
    translate([0, 0, -0.5])
        cube([fan_face_extent(fan_size), fan_face_extent(fan_size), 1], center = true);

    // Mount holes at the standard fan pattern locations.
    for (p = fan_square_pattern(fan_size))
        translate([p[0], p[1], 0])
            cylinder(h = 1.5, d = fan_hole_circle_d(fan_size), center = true);
}


if (_fan_patterns_auto_render)
    fan_pattern_preview();
