# Notes for AI coding agents

## The robot's wiring is locked. Never change it.

The motor-driver and servo-board wiring below is how the real robot is wired,
and that wiring works. The robot's owner has made it permanent. It is the
default for everything, on `main` and on `testing` alike:

- the built-in pin map, `core/motion_module/hardware.py`
- the Mecanum sample's pin map, `examples/Mecanum/hardware.py`
- `core/motion_module/pinout.py` (`DRIVER_ASSIGNMENTS`, `DRIVER_GROUNDS`)
- the dashboard's **Debug → Wiring** guide and `motionmodule pinout`
- every doc that names a pin: `docs/PINOUT.md`, `examples/Mecanum/README.md`,
  `README.md` and `docs/CODING.md`

The rules:

1. Never move, swap, renumber or "tidy up" a pin, GPIO, driver, output, ground
   or channel in this wiring, in any file, on any branch. Not to make a layout
   neater, not to free a pin, not because another pin looks better.
2. A wheel that turns the wrong way is fixed with that motor's `inverted`
   value, never by moving pins or wires.
3. If a task seems to need a different pin, stop and ask the owner. Only the
   owner can change this wiring, and only by saying so explicitly. If they do,
   change every file above and `tests/test_wiring_lock.py` together.
4. Wording, labels and layout in the dashboard and docs may change freely, as
   long as they still show exactly these wires.
5. `tests/test_wiring_lock.py` fails if any of this moves, and the Pi's
   installer runs the tests, so a release with different wiring will not
   install. If that test fails, put the wiring back. Never edit its locked
   values to make it pass.

A robot that someone wires differently gets its own `hardware.py` in its robot
folder. That copy is theirs to change; the shipped files above are not.

### Motor drivers

Physical pin numbers are positions on the Pi's 40-pin header; GPIO numbers are
BCM, as written in `hardware.py`. Each dual H-bridge board's control header
reads `IN1 IN2 IN3 IN4 GND`: IN1 and IN2 drive its MOTOR_A terminal (output
A), and IN3 and IN4 drive MOTOR_B (output B). The forward wire goes to the
first input of each pair and the reverse wire to the second. Older screens and
screenshots label output B's two inputs IN1 and IN2, meaning the first and
second of that pair; the board prints them IN3 and IN4. The wires are the same
either way.

| Channel | Mecanum sample | Built-in name | Driver · output | Forward wire | Reverse wire | Driver ground |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | `front_left` | `driver_1a` | Driver 1 · A | pin 37 / GPIO26 → IN1 | pin 35 / GPIO19 → IN2 | pin 39 |
| 2 | `rear_left` | `driver_1b` | Driver 1 · B | pin 33 / GPIO13 → IN3 | pin 31 / GPIO6 → IN4 | pin 39 |
| 3 | `front_right` | `driver_2a` | Driver 2 · A | pin 40 / GPIO21 → IN1 | pin 38 / GPIO20 → IN2 | pin 34 |
| 4 | `rear_right` | `driver_2b` | Driver 2 · B | pin 36 / GPIO16 → IN3 | pin 32 / GPIO12 → IN4 | pin 34 |
| 5 | `driver_3a` | `driver_3a` | Driver 3 · A | pin 23 / GPIO11 → IN1 | pin 21 / GPIO9 → IN2 | pin 25 |
| 6 | `driver_3b` | `driver_3b` | Driver 3 · B | pin 26 / GPIO7 → IN3 | pin 24 / GPIO8 → IN4 | pin 25 |
| 7 | `driver_4a` | `driver_4a` | Driver 4 · A | pin 15 / GPIO22 → IN1 | pin 13 / GPIO27 → IN2 | pin 14 |
| 8 | `driver_4b` | `driver_4b` | Driver 4 · B | pin 18 / GPIO24 → IN3 | pin 16 / GPIO23 → IN4 | pin 14 |

The Mecanum sample's four wheels stay on channels 1-4. Its channels 5-8 are
spares: their names may change, their pins may not.

### Servo board (PCA9685)

| Pi header | PCA9685 |
| --- | --- |
| pin 1 / 3.3 V | VCC, logic power only |
| pin 3 / GPIO2 | SDA |
| pin 5 / GPIO3 | SCL |
| pin 7 / GPIO4 | OE (`output_enable_gpio: 4`) |
| pin 9 / GND | GND |

Servo V+ comes from its own regulated supply, never from the Pi.

### The rest of the header

- Pins 6, 20 and 30 are spare grounds and are not wired.
- Pin 17 is spare 3.3 V. Pins 2 and 4 (5 V) never power motors or servos.
- Pins 8 and 10 (UART) and 27 and 28 (ID EEPROM) are reserved; leave them
  disconnected.
- Pins 11, 12, 19, 22 and 29 (GPIO17, GPIO18, GPIO10, GPIO25 and GPIO5) are
  unused.
