# Heat-Set Inserts and Printed Threads

This project relies on M2.5 fasteners for the Pi carrier. You can use brass heat‑set inserts for maximum strength or print the threads directly to avoid the extra hardware. Both methods require careful sizing and a bit of practice.

## Heat‑set brass inserts

Heat‑set inserts are knurled brass cylinders that melt into a printed hole. Once cooled they provide durable metal threads.

- Choose inserts with an outer diameter around **3.5 mm** and **4 mm** length for M2.5 screws.
- Size the hole **0.1–0.2 mm smaller** than the insert’s outer diameter so the plastic grips the knurling.
- Use a soldering iron with a flat or conical tip. Set it around **200–220 °C** and press the insert flush with gentle downward pressure.
- Let each insert cool for a few seconds before removing the tip to avoid pulling it back out.

### Safety tips

- Work in a well‑ventilated area and keep the hot iron away from flammable items.
- Hold the part with pliers or tweezers to protect your fingers from the heat.
- If the insert binds or skews, reheat and straighten rather than forcing it.

## Printed threads

You can skip inserts by printing internal threads. The provided OpenSCAD model supports a `standoff_mode` of `"printed"` which generates an M2.5 thread using a simple helix.

```bash
openscad -D standoff_mode="printed" -o triple_printed.stl cad/pi_cluster/pi5_triple_carrier_rot45.scad
```

Printed threads work best with a fine nozzle (0.4 mm or smaller) and four or more perimeters around each standoff. Thread the screw gently the first time to clear any leftover plastic.

## General tips for beginners

- **CAD:** OpenSCAD parameters are plain text values near the top of each file. Adjust them to move boards or change standoff sizes, then preview with `openscad`.
- **3D printing:** Use PLA or PETG with at least 40 % infill for structural parts. Ensure your printer is calibrated so holes come out accurately.
- **Soldering:** Keep your iron clean and tinned. Rest it in a safe stand when not in use.
- **Assembly:** Test‑fit the hardware before final tightening. If threads feel rough, back out and remove any debris.
