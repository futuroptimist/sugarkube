## [Unreleased]
### Added
* pi_carrier: rounded base corners via new `corner_radius` parameter
* panel_bracket: parameterise screw size via `screw_nominal`
* panel_bracket: add `nut` standoff_mode for captive hex recess
* pi5_triple_carrier_rot45: add `nut` standoff_mode for captive hex nuts

### Changed
* panel_bracket: increase default edge radius to 2 mm for smoother corners

### Fixed
* pi_carrier: standoff length increased from 20 mm to 22 mm (flush fit with PoE HAT)
* panel_bracket: add chamfers to printed mounting hole for easier screw insertion
* lint workflow test now uses `actions/checkout@v4` to avoid Node 16 deprecation warnings
