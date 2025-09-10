# Safety

This setup uses a 12 V LiFePO4 battery and outdoor wiring. Follow these precautions:

- Place a 60 A fuse within 7 in (18 cm) of the battery positive terminal.
- Use a battery management system (BMS) to prevent over‑charge and over‑discharge.
- Keep the MPPT charge controller in a ventilated enclosure, never sealed inside the battery box.
- Disconnect the solar panels before wiring the controller to avoid live voltage.
- Fuse the air pump branch at 15 A and the Raspberry Pi buck converter at 5 A.
- Size wiring for the expected current; undersized conductors can overheat.
- Verify polarity with a multimeter before powering devices.
- Disconnect the battery before working on wiring and remove metal jewelry to avoid shorts.
- Add a DC-rated disconnect switch on the battery positive lead so you can kill power quickly and isolate it during maintenance.
- Route cables with drip loops so water cannot run into connectors; use cable glands and strain relief.
- Bond the aluminium frame and charge controller to earth ground where local code requires.
- Use tinned copper lugs and UV-resistant wiring for outdoor runs.
- Refer to [Power System Design](power_system_design.md) for wire and fuse sizing guidelines.
- Wear eye protection while crimping and avoid short circuits when working on the battery.
- Wear insulated gloves along with eye protection when handling the battery or live circuits.
