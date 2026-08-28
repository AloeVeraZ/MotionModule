# MotionModule pinout and power wiring

Software uses **BCM GPIO numbers**. Connector diagrams use **physical header
numbers**. Every table below shows both; never assume they are interchangeable.

## Four dual H-bridge boards

Each GODIYMODULES board controls two motors and has four signal inputs. Connect
each motor only to its own output pair. The names `IN1`/`IN2` below mean the two
direction inputs for that motor; match them to the board's A/B input labels.

| Driver | Output | Motor channel | Default use | IN1 | IN2 | Pi ground |
| ---: | :---: | ---: | --- | --- | --- | --- |
| 1 | A | 3 | Front right | physical 38 / GPIO20 | physical 40 / GPIO21 | physical 39 |
| 1 | B | 4 | Rear right | physical 37 / GPIO26 | physical 33 / GPIO13 | physical 39 |
| 2 | A | 1 | Front left | physical 32 / GPIO12 | physical 31 / GPIO6 | physical 34 |
| 2 | B | 2 | Rear left | physical 35 / GPIO19 | physical 36 / GPIO16 | physical 34 |
| 3 | A | 5 | Extra motor A | physical 29 / GPIO5 | physical 22 / GPIO25 | physical 20 |
| 3 | B | 6 | Extra motor B | physical 21 / GPIO9 | physical 23 / GPIO11 | physical 20 |
| 4 | A | 7 | Extra motor C | physical 24 / GPIO8 | physical 26 / GPIO7 | physical 25 |
| 4 | B | 8 | Extra motor D | physical 16 / GPIO23 | physical 18 / GPIO24 | physical 25 |

Drivers 1 and 2 preserve the supplied physical pin 30–40 block. Physical pin
30 is another available Pi ground but is not required by the reference harness.
Drivers 3 and 4 use the safe signals in physical pins 20–29, plus pins 16 and
18. There are not eight usable signals in 20–29 alone:

| Physical pin | Function in this design |
| ---: | --- |
| 20 | Ground — Driver 3 reference |
| 21 | GPIO9 — Driver 3 B IN1 |
| 22 | GPIO25 — Driver 3 A IN2 |
| 23 | GPIO11 — Driver 3 B IN2 |
| 24 | GPIO8 — Driver 4 A IN1 |
| 25 | Ground — Driver 4 reference |
| 26 | GPIO7 — Driver 4 A IN2 |
| 27 | GPIO0 / ID_SD — **leave disconnected** |
| 28 | GPIO1 / ID_SC — **leave disconnected** |
| 29 | GPIO5 — Driver 3 A IN1 |

This direct-GPIO profile intentionally supports four dual drivers/eight motors.
Adding still more direct H-bridges would consume pins reserved for other Pi
interfaces and increase boot-state/PWM complexity. Expand servos freely by I2C;
for more than eight brushed motors, add an addressed motor-control/PWM expansion
board and a new software backend instead of casually taking the ID or UART pins.

GPIO7/8/9/11 normally have alternate SPI functions. The reference Raspberry Pi
OS image has SPI disabled. `motionmodule doctor` warns if a `/dev/spidev*`
device is active; disable SPI before using Drivers 3 and 4.

Install a 10 kΩ pull-down resistor from every one of the 16 driver inputs to
signal ground, preferably at the driver connector. Raspberry Pi GPIOs are inputs
during early boot and cannot be relied on to hold an H-bridge input low until
Linux and the service have started. Keep motor power physically switched off
during boot until these pull-downs and the stopped-output behavior are verified.

## PCA9685 servo controller

The servo board is a separate I2C device and shares no motor GPIO.

| PCA9685 connection | Raspberry Pi / supply connection |
| --- | --- |
| SDA | physical pin 3 / GPIO2 |
| SCL | physical pin 5 / GPIO3 |
| VCC (logic) | physical pin 1 / 3.3 V |
| GND | physical pin 6 / ground |
| V+ screw terminal | separate regulated servo supply positive |
| V+ screw terminal GND | servo supply negative and common logic ground |

> [!WARNING]
> `VCC` powers PCA9685 logic. `V+` powers the servos. Do not bridge them and do
> not power a bank of servos from a Raspberry Pi 5 V header pin.

The first board has every address pad open and uses `0x40`. To add another
board, solder A0 on the second board for `0x41`, chain SDA/SCL/VCC/GND, provide
appropriately sized servo power, and edit:

```toml
[servos]
addresses = [0x40, 0x41]
```

Code then uses `module.servo(channel=0, board=1)` for the second board. Never
put two boards with the same address on one bus. The hardware can address many
boards, but wire length, bus capacitance, connector current, and power
distribution become the practical limits well before the advertised maximum.

## Power boundaries

Use three planned power domains:

1. Raspberry Pi logic power from a stable Pi-rated 5 V regulator.
2. Motor power from the robot battery through a main switch and correctly sized
   fuses to each driver branch.
3. Servo power from a separate regulated rail set for the connected servos,
   normally 5–6 V for standard hobby servos.

Join their negatives at a deliberate common reference point so 3.3 V control
signals have a return path. Do **not** route motor current through a Pi ground
pin: the heavy driver power negatives return directly to the battery/power
distribution bus, while the Pi ground wires are only low-current signal
references.

The Amazon listing's 10 A figure does not override a motor's stall-current
requirement. Measure or obtain each motor's stall current, fuse below the safe
wire/connector/driver limit, and add the recommended heat sinking/airflow for
high continuous current. Use one motor per H-bridge channel.

## First electrical test

1. Disconnect battery and servo power.
2. Verify every BCM/physical pin against the tables with a continuity meter.
3. Verify no motor supply positive is connected to a Pi header pin.
4. Set the servo regulator voltage before attaching servos.
5. Put the chassis on a stable stand with all wheels clear.
6. Confirm every driver input has its 10 kΩ pull-down, power the Pi first, and
   run `motionmodule doctor`.
7. Apply motor power with the physical cutoff in reach.
8. Stop the service and pulse one channel: `motionmodule stop`, then
   `motionmodule test-motor 1`.
9. Test each channel and label the resulting physical wheel/mechanism.
10. Restart normal code only after the map is verified: `motionmodule start`.
