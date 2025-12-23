# Pi carrier stack export_part ignored on Windows

## Summary

`openscad -D export_part="carrier_level" cad/pi_cluster/pi_carrier_stack.scad` on Windows
PowerShell rendered the full three-level stack instead of a single carrier and printed
`export_part = undef` alongside warnings about an unknown variable `carrier_level`.

## Impact

- Single-part exports (`carrier_level`, `post`) silently rendered the entire stack.
- Console output contained distracting warnings: `Ignoring unknown variable 'carrier_level'`.
- Dimension/geometry reports misreported `export_part`, making CLI-driven automation unreliable.

## Root cause

`export_part` relied on shell-provided quoting. On PowerShell, the `-D export_part="carrier_level"`
flag arrived as the bare identifier `carrier_level`, which OpenSCAD treated as an undefined variable
and preserved as `undef`. The stack wrapper compared `export_part` directly without normalizing or
providing string-backed tokens, so the requested part was ignored and the fallback assembly rendered.
`pi_stack_post.scad` echoed the same warning when imported because the undefined identifier leaked
into its scope.

## Resolution

- Added string-backed part selectors (`carrier_level`, `post`, `assembly`) and normalized
  `export_part` to a string before branching so CLI overrides survive shell quoting differences.
- Declared a `carrier_level` string in `pi_stack_post.scad` to prevent undefined-identifier warnings
  when it is rendered directly.
- Documented PowerShell and bash invocations that keep `export_part` intact and added a static test to
  guard against bare identifier comparisons.

## Reproduction

- **PowerShell (before fix):**

  ```powershell
  openscad `
    -o "$env:TEMP\ignore.stl" `
    -D 'export_part="carrier_level"' `
    -D 'emit_dimension_report=true' `
    -- cad/pi_cluster/pi_carrier_stack.scad
  ```

  Warnings included `Ignoring unknown variable 'carrier_level'` and the dimension report echoed
  `export_part = undef` while rendering the full assembly.

- **Bash (before fix):**

  ```bash
  openscad -o /tmp/ignore.stl -D export_part="carrier_level" \
    -D emit_dimension_report=true cad/pi_cluster/pi_carrier_stack.scad
  ```

  The same warning appeared and the assembly rendered instead of a single carrier level.

## Verification

- **PowerShell (after fix):**

  ```powershell
  openscad `
    -o "$env:TEMP\pi_carrier_stack_level.stl" `
    -D 'export_part="carrier_level"' `
    -D 'emit_dimension_report=true' `
    -D 'emit_geometry_report=true' `
    -- cad/pi_cluster/pi_carrier_stack.scad
  ```

  Expected console snippet:

  ```text
  ECHO: "pi_carrier_stack", levels = 3, ..., export_part = carrier_level, stack_bolt_d = 3.4
  ```

  No `Ignoring unknown variable 'carrier_level'` warnings and only a single carrier level renders.

- **Bash (after fix):**

  ```bash
  openscad -o /tmp/pi_carrier_stack_level.stl -D export_part="carrier_level" \
    -D emit_dimension_report=true -D emit_geometry_report=true \
    cad/pi_cluster/pi_carrier_stack.scad
  ```

  The echo payload matches the PowerShell output and renders just the carrier level.

## Follow-ups

- Keep a static test in place to block future regressions to bare identifier comparisons.
- Prefer quoting `export_part` values in docs to minimize cross-shell surprises.
