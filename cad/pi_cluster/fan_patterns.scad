// Helper functions for PC fan geometry shared across the stacked carrier modules.

function fan_hole_spacing(size) =
    size == 120 ? 105 :
    size == 92  ? 82.5 :
    size == 80  ? 71.5 :
    105;

function fan_mount_clearance(size) = 3.4; // Through hole for M3 screws with margin.

function fan_hole_circle_d(size) =
    4.5; // M4/#6 pass-through (oversize for M3 screws per stack doc guidance).

function fan_square_pattern(size, spacing = fan_hole_spacing(size)) =
    let(half = spacing / 2)
        [
            [-half, -half],
            [half, -half],
            [-half, half],
            [half, half],
        ];

function fan_face_extent(size) = size + 24; // Adds a 12 mm rim on each edge for stiffness.
