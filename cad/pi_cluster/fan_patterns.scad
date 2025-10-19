// Helper functions for PC fan geometry shared across the stacked carrier modules.

function fan_hole_spacing(size) =
    size == 120 ? 105 :
    size == 92  ? 82.5 :
    size == 80  ? 71.5 :
    105;

function fan_mount_clearance(size) = 3.4; // Through hole for M3 screws with margin.

function fan_face_extent(size) = size + 24; // Adds a 12 mm rim on each edge for stiffness.
