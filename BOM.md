# MotionModule bill of materials

The reference hardware for one eight-motor, sixteen-servo MotionModule robot.
The whole machine runs from a **single 12 V battery**: the motor drivers take
that 12 V directly, the Raspberry Pi gets 5 V from a USB-C converter, and the
servos get their own regulated rail.

The same list is built into the dashboard under **Debug → Parts list**, so it
works on the robot hotspot with no internet connection.

**The first two sections are the robot.** Buy those and MotionModule boots,
serves its dashboard and drives outputs. Everything after them — motors,
servos, wire — is a recommendation, not a requirement.

---

## Required · Controller and control boards

| Qty | Part | Selection | Purpose |
| ---: | --- | --- | --- |
| 1 | Raspberry Pi 5 | 40-pin GPIO header; 4 GB is sufficient | Runs MotionModule, the dashboard, Wi-Fi, and robot code |
| 1 | microSD card | 32 GB or larger, Application Performance Class A2 recommended | Raspberry Pi OS and versioned releases |
| 1 | Pi 5 active cooler | [Argon THRML 30 mm active cooler](https://argon40.com/products/argon-thrml-30mm-active-cooler) | Prevents thermal throttling in an enclosed robot |
| 4 | Dual H-bridge motor driver | [GODIYMODULES DC 3–18 V, dual H-bridge PWM driver](https://www.amazon.com/dp/B0FKH352D2) | Two brushed motors per board; eight channels total |
| 1 | 16-channel servo controller | [AITRIP PCA9685](https://www.amazon.com/dp/B07WS5XY63) at address `0x40`, all pads open | Sixteen servo PWM channels over I²C |
| 1 set | Controller mounting CAD | [`cad/` in this repository](https://github.com/AloeVeraZ/MotionModule/tree/main/cad) | Printable mounts holding the Pi, drivers and servo board together |

The PCA9685 confirms over I²C that its logic is present, but it cannot report
whether an individual servo is plugged into an output. The H-bridge inputs have
no return path at all, so a configured motor channel is never proof of a
connection.

## Required · Power module

| Qty | Part | Selection | Status |
| ---: | --- | --- | --- |
| 1 | 12 V battery | [goBILDA 12 V NiMH, 3000 mAh, XT30](https://www.gobilda.com/12v-nimh-nested-battery-3000mah-mh-fc-xt30-connector/) | Selected |
| or | 12 V battery | [REV 12 V Slim, 3000 mAh, XT30](https://www.revrobotics.com/rev-31-1302/) — inline 20 A replaceable ATM fuse | Selected |
| 1 pack | XT30 pigtails | [XT30 male & female leads on silicone wire](https://www.amazon.com/dp/B0FY2ZCR83) | Selected |
| 1 | 12 V → 5 V USB-C converter | [Amazon B0FD735LFG](https://www.amazon.com/dp/B0FD735LFG) | Selected |
| 1 | Rocker switch | [DaierTek KCD1 automotive rocker switch](https://www.amazon.com/DaierTek-Listed-Switches-Automotive-KCD1-5Pack/dp/B07S1MV462) | Selected |
| 1 | 12 V/24 V → 5 V 5 A buck converter | [PlusRoc waterproof buck converter, 2-pack](https://www.amazon.com/dp/B0FYNCSV2Z) | Selected |
| 1 set | Power module CAD | [`cad/` in this repository](https://github.com/AloeVeraZ/MotionModule/tree/main/cad) | **Being drawn** |

**Both batteries ship with their own fuse**, so there is no separate fuse or
breaker to buy. The rocker switch is the physical cutoff. **The buck converter
above steps the 12 V battery rail down to the PCA9685's servo V+ terminal**,
which is rated 3.3–6 V; the converter's fixed 5 V output sits safely inside
that range. It outputs 5 A (25 W) maximum — size how many servos you run at
once against that budget.

> [!WARNING]
> **V+ feeds every servo directly.** The board will take up to 12 V there, but
> hobby servos want 5–6 V and an Axon Mini MK2 tops out at 8.4 V, so give V+ the
> stepped-down rail rather than the battery. The **V+ header pin is the same net
> as the screw terminal**, so it already carries the servo rail — wiring it to a
> Pi 5 V pin would put that rail straight into the Pi. Neither the 12 V rail nor
> the servo V+ rail may touch a Raspberry Pi header pin; the Pi is powered only
> through its USB-C input.

---

## Recommended · Motors and servos

None of this is needed to make the controller run. These are the parts known to
work well on it.

| Qty | Part | Selection | Notes |
| ---: | --- | --- | --- |
| Up to 8 | Brushed DC motors | [goBILDA Yellow Jacket planetary gear motors](https://www.gobilda.com/yellow-jacket-planetary-gear-motors) | What we run. **Any brushed DC motor rated for 12 V works** |
| Up to 8 | 3.5 mm bullet lead, MH-FC to bare wire | [goBILDA GB-3800-0013-0300](https://www.gobilda.com/3-5mm-bullet-lead-mh-fc-300mm-length/), 300 mm, 16 AWG | Bullets plug onto the motor; the bare end screws into the driver's terminal block |
| Up to 16 | Servo | [goBILDA Axon Mini MK2](https://www.gobilda.com/axon-mini-servo-mk2/) | **Recommended.** Any Axon servo is a step up: programmable range, mode and centring |
| Alternative | Servo | [Standard three-pin servos](https://www.gobilda.com/standard-size-servos) | Any standard 3-pin hobby servo works; match its voltage to the servo rail |

Each dual H-bridge board is rated **10 A in total, shared between its two
outputs** — that budget covers both motors on the board, not 10 A each. Size
the motors so two of them together stay inside it.

**Motor connectors.** Yellow Jacket motor leads end in 3.5 mm **FH-MC** bullets
(female housing, male contact), so the part that mates with them is the
**MH-FC** lead above. Its bullets push onto the motor and its bare end goes
straight into the driver's screw terminal — no crimping, no adaptor. goBILDA's
*JST VH adaptor* converts those same bullets to a REV Expansion Hub connector
and is not used in this build. Swapping which bullet lands on which terminal
reverses that motor, but set direction with `inverted` in `hardware.py` rather
than in the wiring.

## Recommended · Pi-connected BNO055

The Mecanum robot's IMU connects directly to the Pi on the independent
`i2c-gpio` bus. No Arduino is needed for the reference robot.

| Qty | Part | Selection | Notes |
| ---: | --- | --- | --- |
| 1 | 9-axis IMU | [Teyleten Robot BNO055 breakout](https://www.amazon.com/Teyleten-Robot-Attitude-Acceleration-Geomagnetic/dp/B0D47G672B/) | Read by the Pi; address 0x28 |

VIN goes to physical pin 17, GND to 20, SDA to 11, SCL to 12, and AD0 to 6.
Use the [complete wiring guide](docs/PINOUT.md#optional-gy-bno055-nine-axis-imu)
and [Pi IMU setup](docs/CODING.md#pi-connected-bno055-imu). The robot can drive
without the IMU, but heading will be unavailable.

## Optional · USB GPIO expansion

| Qty | Part | Selection | Notes |
| ---: | --- | --- | --- |
| Optional | USB GPIO board | [Arduino GIGA R1 WiFi, ABX00063](https://store-usa.arduino.cc/products/giga-r1-wifi) | USB-C data cable to the Pi; GPIO inputs take 3.3 V maximum |

This is an experimental extension for future sensors, not part of the
Mecanum wiring. USB auto-detection, bridge firmware and a Python pin API are
included; operation with your hardware needs verification. No extra sensors
are selected or declared. The firmware targets GIGA, not Uno or Mega.
See [USB expansion setup](docs/SETUP.md#optional-usb-gpio-expansion).

## Recommended · Wiring

| Qty | Part | Requirement |
| ---: | --- | --- |
| As needed | Jumper wires | [Multicoloured breadboard jumper set](https://www.amazon.com/Elegoo-EL-CP-004-Multicolored-Breadboard-arduino/dp/B01EV70C78); female-to-female for the Pi header |
| As needed | Wago 221 lever connectors | [Wago 221-2401 compact splicing connectors](https://www.amazon.com/221-2401-Compact-Splicing-Inline-Connectors/dp/B0BT8DHLJJ) for every 12 V join |
| As needed | 16 AWG silicone wire | [Haerkn 16 AWG silicone wire, two cores, tinned copper, 25 ft](https://www.amazon.com/dp/B07RRPFL3Q) for the 12 V battery and motor runs, up to the 10 A each driver draws |

That is the whole wiring list. Control signals are ordinary jumper wires from
the Pi header, every 12 V and motor run is 16 AWG silicone wire, every 12 V
join is a Wago connector, and the boards, motors and servos all arrive with
their own leads. The wire's red core is positive and its black core negative.

Raspberry Pi GPIOs are inputs during early boot, so keep motor power switched
off until you have watched the outputs stay still. If one driver twitches at
boot, a 10 kΩ pull-down from that input to signal ground holds it low.

## Recommended · Tools for setup

- Digital multimeter with continuity and DC-voltage modes.
- Current-limited bench supply when available.
- Stable robot stand that keeps every wheel off the floor.
- Small screwdriver set and wire stripper.

---

## Still to decide

1. The CAD files themselves — both `cad/` folders are still being filled in.

The complete signal wiring is in [docs/PINOUT.md](docs/PINOUT.md).
