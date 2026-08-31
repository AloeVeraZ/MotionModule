# MotionModule bill of materials

This is the reference hardware list for one eight-motor MotionModule robot. The
two linked control boards are the exact products selected for this project.
Items marked **size after measurement** cannot be chosen safely until the motor
stall current, servo stall current, battery voltage, and wire lengths are known.

## Controller and control boards

| Qty | Part | Exact selection / requirement | Purpose |
| ---: | --- | --- | --- |
| 1 | Raspberry Pi 5 | 40-pin GPIO header; 4 GB is sufficient | Runs MotionModule, the dashboard, Wi-Fi, and robot code |
| 1 | microSD card | 32 GB or larger, Application Performance Class A2 recommended | Raspberry Pi OS and versioned releases |
| 1 | Raspberry Pi 5 Active Cooler or fan case | [Official Active Cooler](https://www.raspberrypi.com/products/active-cooler/) | Prevents thermal throttling in an enclosed robot |
| 4 | Dual H-bridge motor driver | [GODIYMODULES DC 3–18 V, dual H-bridge PWM driver](https://www.amazon.com/dp/B0FKH352D2) | Two brushed motors per board; eight total channels |
| 1 installed | 16-channel servo controller | [AITRIP PCA9685 two-board pack](https://www.amazon.com/dp/B07WS5XY63); use address `0x40` for the first board | Sixteen servo PWM channels over I²C |
| 1 spare / optional | Second PCA9685 from the same pack | Solder A0 and configure address `0x41` before connecting both boards | Adds another sixteen servo channels |

The motor driver's advertised current is not a safe system design value by
itself. Verify every motor's measured or documented stall current and provide
cooling as required. The PCA9685 confirms that its logic is present over I²C,
but it cannot report whether an individual servo is plugged into an output.

## Motors, servos, and robot power

| Qty | Part | Selection rule | Status |
| ---: | --- | --- | --- |
| Up to 8 | Brushed DC gearmotors | Motor voltage must match the battery and remain within the driver's 3–18 V range; record stall current | **Motor model required** |
| As needed | Hobby servos | Voltage must match the regulated servo rail; record running and stall current | **Servo model and quantity required** |
| 1 | Robot battery | Match the motors and expected total load | **Size after measurement** |
| 1 | Raspberry Pi power converter | Stable Pi-rated 5 V supply with enough current and a protected USB-C connection | **Size after battery selection** |
| 1 | Servo BEC / regulator | Normally 5–6 V; continuous and peak ratings must cover all simultaneously moving servos | **Size after servo selection** |
| 1 | Main fuse or circuit breaker | Below the battery, connector, main-wire, and distribution limits | **Size after current calculation** |
| 4 | Motor-driver branch fuses | One protected battery branch per H-bridge board | **Size after motor stall-current calculation** |
| 1 | Main power switch / physical cutoff | DC-rated for the robot battery and maximum expected current | Required |
| 1 | Power distribution block | Separate fused branches for Pi logic, servo power, and motor power | Required |

For bench setup, Raspberry Pi recommends a 5 V / 5 A supply for Raspberry Pi 5;
its official option is the 27 W USB-C supply. Do not power motors or a bank of
servos from the Pi's header. See the
[official Raspberry Pi power guidance](https://www.raspberrypi.com/documentation/computers/getting-started.html#recommended-power-supply).

## Wiring and protection

| Qty | Part | Requirement |
| ---: | --- | --- |
| 16 | 10 kΩ resistors | One pull-down from every H-bridge input to signal ground, placed at the driver connector |
| 1 set | 40-pin GPIO harness or breakout | Must preserve physical pin numbering and provide strain relief |
| 4 sets | Motor-driver signal connectors | Four control signals plus low-current Pi ground reference per driver |
| 8 sets | Motor output connectors | One appropriately rated two-wire output connection per motor |
| As needed | Motor and battery wire | Stranded copper; gauge and insulation sized for stall/fault current and length |
| As needed | Servo extensions / distribution | Rated for the combined servo current; do not pass bank current through thin daisy chains |
| As needed | Signal wire | Stranded 22–26 AWG is typical for short GPIO/I²C runs; use secure connectors |
| 1 set | Common-ground distribution | Joins Pi signal ground, driver signal reference, battery negative, and servo-regulator negative at a planned point |
| As needed | Ferrules, heat-shrink, loom, and strain relief | Prevents loose strands, connector pullout, and abrasion |
| 4 | Driver heatsinks or directed airflow provisions | Required when testing shows significant driver heating |

## Setup and test equipment

These tools are not installed on the robot, but they are required for safe
assembly and commissioning:

- Digital multimeter with continuity and DC-voltage modes.
- Current-limited bench supply when available.
- Correct crimp tool and terminals for the chosen connectors.
- Stable robot stand that keeps every wheel off the floor.
- Small screwdriver set, wire stripper, and fuse assortment.

## Before purchasing the remaining power parts

Record these values in the robot build notes:

1. Motor model, rated voltage, and stall current for all eight motors.
2. Servo model, quantity, voltage, and stall current.
3. Battery chemistry, nominal voltage, maximum voltage, and discharge rating.
4. Longest high-current wire run and connector ratings.
5. Whether the robot must run untethered or may use the official Pi supply on a bench.

Those measurements determine the battery, regulators, fuses, wire gauges,
connectors, power distribution, and cooling. The complete signal wiring is in
[docs/PINOUT.md](docs/PINOUT.md).
