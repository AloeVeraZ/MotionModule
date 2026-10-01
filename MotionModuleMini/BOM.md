# MotionModule Mini bill of materials

Four brushed-motor outputs, sixteen servo outputs and the Pi-connected MPU6500.
This list is also available offline in the Mini dashboard under Debug → Parts list.

| Quantity | Part | Selection |
| ---: | --- | --- |
| 1 | Raspberry Pi 5 | 4 GB is sufficient |
| 1 | microSD card | 32 GB or larger, A2 recommended |
| 1 | Active cooler | [Argon THRML 30 mm](https://argon40.com/products/argon-thrml-30mm-active-cooler) |
| 2 | Dual H-bridge motor driver | [GODIYMODULES DC 3–18 V](https://www.amazon.com/dp/B0FKH352D2); two motors per board |
| 1 | PCA9685 servo controller | [AITRIP PCA9685](https://www.amazon.com/dp/B07WS5XY63), 0x40, all address pads open; 16 servo outputs |
| 1 | MPU6500 IMU | [Reference module](https://www.amazon.com/dp/B0GTVCCY6B); same independent Pi I²C bus |
| 1 assortment | Self-tapping screws | [Fasvicna M1.7–M3, 750 pieces](https://www.amazon.com/dp/B0H8CK9QVW) |
| Up to 4 | Brushed 12 V motors | [goBILDA Yellow Jacket](https://www.gobilda.com/yellow-jacket-planetary-gear-motors), or another suitable 12 V brushed motor |
| Up to 4 | Motor bullet leads | [goBILDA MH-FC to bare wire](https://www.gobilda.com/3-5mm-bullet-lead-mh-fc-300mm-length/) |
| Up to 16 | Servos | Same servo choices and regulated power requirements as the full module |

![Fasvicna self-tapping screw assortment](../docs/images/fasvicna-self-tapping-screws.png)

Use **four M2.3 × 5 mm self-tapping screws** for the Pi. Use **M3 × 5 mm**
for the two motor-driver boards, PCA9685 and IMU, one per mounting hole.
The Mini enclosure and its corner screw count must follow its final CAD;
the full enclosure's 22-M3-screw total is not a Mini specification.

Use the same [power module](../BOM.md#required--power-module): 12 V battery,
XT30 leads, cutoff switch, Pi USB-C converter, regulated 5 V / 5 A servo
converter and electronics box. The two driver boards each share a 10 A budget
between their two motor outputs. Servo current remains limited by the same
5 A converter. Keep motor and servo power away from Pi header power pins.

Use the same [wire, connectors and setup tools](../BOM.md#recommended--wiring).
Mini has no Drivers 3 or 4 and no motor channels 5–8. Mini enclosure CAD is not
included; the [power-box CAD](../cad/electronics-box.step) is still available.
See the [Mini pinout](PINOUT.md) before connecting the robot.
