# Power System Design

This section dives deeper into sizing batteries and choosing a charge controller for more advanced setups.

## Batteries
Several chemistries are common in small solar installations:
- **Lead-acid** (SLA or AGM) – inexpensive but heavy and less tolerant of deep discharge.
- **LiFePO4** – lightweight and long-lived, ideal for off-grid electronics.

Choose a capacity large enough for a day or two of autonomy.
Multiply your daily watt-hour use by the number of backup days, then divide by the battery's usable
depth of discharge (0.8 for LiFePO4, ~0.5 for lead-acid).

## Charge Controllers
A controller regulates the energy from the panels into the battery.

### PWM vs MPPT
- **PWM** controllers are inexpensive but waste excess panel voltage as heat.
- **MPPT** units track the optimal voltage to harvest more power, especially in cold or shaded conditions.

For a four-panel array, a 20 A MPPT controller provides room to grow and keeps charging efficient.

## Energy Budget Example
A Raspberry Pi draws roughly 10 W. Running 24 h uses 240 Wh. Add 20 Wh for a small air pump and 40 Wh for conversion losses for a total of ~300 Wh per day.

To provide two days of reserve you would want a 12 V battery rated at least 600 Wh (about 50 Ah). Combine that with 400 W of solar panels and an MPPT charge controller for reliable operation.

Continually monitor voltage and temperature to prolong battery life.
