# Solar Power Basics

This primer explains how photovoltaic panels convert sunlight into electricity and how to size a simple system.

## Key Terms
- **Voltage (V)** – Electrical "pressure" that drives current. Typical panels produce around 18 V in full sun.
- **Current (A)** – The flow of electrons. Multiply voltage by current to get **power** in watts.
- **Watt-hours (Wh)** – One watt of power used for an hour. Batteries are often rated in watt-hours or amp-hours (Ah).

## How Panels Work
Silicon cells generate a voltage when exposed to light. Cells are wired in series to increase voltage and in parallel to increase current. A 100 W panel might produce about 18 V at 5.5 A in bright sun.

### Orientation
- Face panels toward the equator for maximum exposure.
- Tilt roughly equal to your latitude.
- Keep the surface free of shade and dirt.

### Connecting Panels
- **Series** connections add voltage but keep current the same.
- **Parallel** connections add current but keep voltage the same.
- Use outdoor‑rated connectors and wire gauges sized for the expected current.

### Charge Controllers
Never connect panels directly to a battery. Route them through a charge controller
which regulates voltage and prevents overcharging. Attach the controller to the battery first,
then connect the panel leads so the controller powers up safely. Add appropriately sized
fuses or DC breakers on the panel and battery leads to protect wiring from shorts.

## Example Budget
Four 100 W panels wired in parallel can deliver roughly 20 A at 18 V to the charge controller.
Over a six‑hour sunny day this yields about 2 kWh (20 A × 18 V × 6 h ≈ 2.1 kWh).

That energy then charges the battery and powers small loads like an aquarium pump or Raspberry Pi.

See [power_system_design.md](power_system_design.md) for guidance on sizing batteries and selecting a controller.
