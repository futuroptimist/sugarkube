# OpenSCAD export_part ignored on PowerShell

## Summary
When rendering `cad/pi_cluster/pi_carrier_stack.scad` from Windows PowerShell with `-D export_part="carrier_level"`, OpenSCAD produced warnings about an unknown variable `carrier_level`, rendered the full three-level assembly, and echoed `export_part = undef` in the dimension report. Bash users did not always hit the problem, so the regression initially looked platform-specific.

## Root cause
PowerShell stripped the double quotes inside `-D export_part="carrier_level"`, so OpenSCAD evaluated `carrier_level` as a bare identifier instead of a string literal. The wrapper treated the undefined token as `undef`, skipped the carrier-only branch, and forwarded the warning from OpenSCAD about the unknown identifier. The SCAD file lacked any guardrails to coerce non-string inputs back into the expected string values, so the CLI override was silently ignored.

## Resolution
- Normalize `export_part` to a string (falling back to `"assembly"` only when `export_part` is undefined) and explicitly match the known part selectors (`"carrier_level"`, `"post"`, `"assembly"`).
- Document cross-platform invocation patterns so PowerShell users pass a preserved string literal.
- Add a static test to block future uses of bare identifiers in `export_part` comparisons.

## Reproduction (pre-fix)
- PowerShell (renders full assembly, emits warnings):
  ```powershell
  openscad `
    -o "$env:TEMP\pi_carrier_stack.stl" `
    -D "export_part=\"carrier_level\"" `
    -D "emit_dimension_report=true" `
    -- cad/pi_cluster/pi_carrier_stack.scad
  ```
  - Expected bad output: warnings like `Ignoring unknown variable 'carrier_level'` and an echo line containing `export_part = undef`.

## Verification (post-fix)
- Bash:
  ```bash
  openscad -o /tmp/pi_carrier_stack.stl \
    -D export_part="carrier_level" \
    -D emit_dimension_report=true \
    -- cad/pi_cluster/pi_carrier_stack.scad
  ```
- PowerShell:
  ```powershell
  openscad `
    -o "$env:TEMP\pi_carrier_stack.stl" `
    -D "export_part=\"carrier_level\"" `
    -D "emit_dimension_report=true" `
    -- cad/pi_cluster/pi_carrier_stack.scad
  ```
- Expected output snippet (no warnings):
  ```
  ECHO: "pi_carrier_stack", levels = 3, ..., export_part = carrier_level, stack_bolt_d = 3.4
  ```
- Static guard: `pytest tests/test_export_part_static_guard.py` ensures `export_part` comparisons stay string-literal-safe even when CLI quoting is imperfect.

## Follow-ups
- None; default assembly renders remain unchanged when `export_part` is unset.
