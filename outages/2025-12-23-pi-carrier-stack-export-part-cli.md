# OpenSCAD export_part ignored on Windows

## Summary
OpenSCAD renders the full Pi carrier stack and logs `export_part = undef` even when
`-D export_part="carrier_level"` is provided. PowerShell runs also emit warnings about an unknown
`carrier_level` variable.

## Impact
- Targeted STL exports (single carrier level) could not be generated from PowerShell.
- Logs showed confusing `export_part = undef` entries and "Ignoring unknown variable" warnings.

## Root cause
`export_part` was compared directly without normalizing CLI inputs. In PowerShell the quoted argument
was interpreted as a bare token, so OpenSCAD treated `carrier_level` as an undefined identifier,
logged a warning, and fell back to the default assembly preview.

## Resolution
- Added `_normalize_export_part()` to coerce CLI inputs to strings without overwriting provided
  values.
- Switched part-selection branching and dimension report logging to use the normalized value.
- Documented Bash and PowerShell invocations that keep `export_part` intact and free of warnings.
- Added a static regression test to guard against reintroducing bare token comparisons.

## Reproduction
### Before
```powershell
openscad `
  -o "$env:TEMP\pi_carrier_stack_level.stl" `
  -D 'export_part="carrier_level"' `
  -D 'emit_dimension_report=true' `
  -- cad/pi_cluster/pi_carrier_stack.scad
```

Expected/actual before fix:
- Warnings like `Ignoring unknown variable 'carrier_level'`.
- Dimension report printed `export_part = undef` and rendered the full assembly.

### After
```bash
openscad -o /tmp/pi_carrier_stack_level.stl \
  -D export_part="carrier_level" \
  -D emit_dimension_report=true \
  cad/pi_cluster/pi_carrier_stack.scad
```

```powershell
openscad `
  -o "$env:TEMP\pi_carrier_stack_level.stl" `
  -D 'export_part="carrier_level"' `
  -D 'emit_dimension_report=true' `
  -- cad/pi_cluster/pi_carrier_stack.scad
```

Expected after fix:
- No unknown-variable warnings.
- Dimension report echoes `export_part = carrier_level` and only the carrier level renders.

## Verification
- Static test enforces quoted export_part comparisons in `pi_carrier_stack.scad`.
- Manual runs should match the expected outputs above.
