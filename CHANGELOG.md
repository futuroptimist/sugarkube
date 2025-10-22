## [Unreleased]
### Added
* pi_carrier: rounded base corners via new `corner_radius` parameter
* panel_bracket: parameterise screw size via `screw_nominal`
* panel_bracket: add `nut` standoff_mode for captive hex recess

### Changed
* panel_bracket: increase default edge radius to 4 mm for smoother corners
* panel_bracket: validate `hole_offset` stays within bracket bounds
* pi_carrier: set standoff diameter to 6.5 mm for added strength
* pi_carrier: widen nut recess clearance to 0.4 mm for easier nut insertion
* pi5_triple_carrier_rot45: widen nut recess clearance to 0.4 mm for easier nut insertion
* panel_bracket: enlarge insert to 6.3 mm OD for common M5 heat‑set hardware
* CI: upgrade GitHub-hosted actions to Node 22-compatible majors (`actions/checkout@v5`,
  `actions/setup-python@v6`)
* docs: streamline Raspberry Pi quick start with HA guidance and post-bootstrap checks
* tests: add kubeconfig recipe smoke coverage and expand token selection assertions

### Fixed
* pi_carrier: standoff length increased from 20 mm to 22 mm (flush fit with PoE HAT)
* panel_bracket: add chamfers to printed mounting hole for easier screw insertion
* lint workflow test now uses `actions/checkout@v4` to avoid Node 16 deprecation warnings

### Ergonomics
* Track ergonomics-focused updates directly in the changelog and guard the section with
  `tests/test_changelog.py` so developer-experience improvements stay visible across releases.
