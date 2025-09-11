## [Unreleased]
### Added
* pi_carrier: rounded base corners via new `corner_radius` parameter
* panel_bracket: parameterise screw size via `screw_nominal`
* panel_bracket: add `nut` standoff_mode for captive hex recess

### Changed
* panel_bracket: increase default edge radius to 4 mm for smoother corners
* panel_bracket: validate `hole_offset` stays within bracket bounds
* pi_carrier: set standoff diameter to 6.5 mm for added strength
* pi_carrier: widen nut recess clearance to 0.3 mm for easier nut insertion

### Fixed
* pi_carrier: standoff length increased from 20 mm to 22 mm (flush fit with PoE HAT)
* panel_bracket: add chamfers to printed mounting hole for easier screw insertion
* lint workflow test now uses `actions/checkout@v4` to avoid Node 16 deprecation warnings
