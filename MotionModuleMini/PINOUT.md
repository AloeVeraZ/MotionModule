# MotionModule Mini pinout

Mini retains the locked channels 1–4 from the full module. It uses **two dual
motor drivers for four motors**. Drivers 3 and 4 are omitted; no remaining
connection is moved. Physical pin numbers refer to the Pi 40-pin header;
GPIO numbers are BCM.

![Complete Mini wiring](../docs/images/motionmodule-mini-complete-wiring.png)

| Channel | Default name | Mecanum wheel | Driver / output | Forward wire | Reverse wire | Driver ground |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | driver_1a | front_left | Driver 1 / A | pin 37 / GPIO26 → IN1 | pin 35 / GPIO19 → IN2 | pin 39 |
| 2 | driver_1b | rear_left | Driver 1 / B | pin 33 / GPIO13 → IN3 | pin 31 / GPIO6 → IN4 | pin 39 |
| 3 | driver_2a | front_right | Driver 2 / A | pin 40 / GPIO21 → IN1 | pin 38 / GPIO20 → IN2 | pin 34 |
| 4 | driver_2b | rear_right | Driver 2 / B | pin 36 / GPIO16 → IN3 | pin 32 / GPIO12 → IN4 | pin 34 |

Motor outputs A and B connect to their respective motors. Supply each driver
from switched 12 V and return its power ground directly to battery ground;
Pi ground wires carry the signal reference, not motor current.

## PCA9685: all sixteen servo outputs

| Pi connection | PCA9685 connection |
| --- | --- |
| pin 1 / 3.3 V | VCC, logic only |
| pin 3 / GPIO2 | SDA |
| pin 5 / GPIO3 | SCL |
| pin 7 / GPIO4 | OE, active low |
| pin 9 / GND | Logic GND |

Use address 0x40 with all address pads open. Servo V+ comes from its own
regulated supply; join its return at common ground. Never connect V+ or motor
battery positive to a Pi header pin. All sixteen PWM / V+ / GND output headers
remain available.

## MPU6500: same independent I²C bus

| Pi connection | IMU connection |
| --- | --- |
| pin 17 / 3.3 V | VCC / VIN |
| pin 6 / GND | GND |
| pin 11 / GPIO17 | SDA |
| pin 12 / GPIO18 | SCL |
| pin 20 / GND | AD0, selects 0x68 |

Keep CS high for I²C (verify the board's pull-up); leave INT and auxiliary pins
disconnected. The installer enables `i2c-gpio` with SDA 17 and SCL 18.
Reboot after installation. Use the same [IMU setup and robot API](../docs/CODING.md#pi-connected-mpu6500-imu).

## Unused pins

The former Driver 3 and 4 signal pins (13, 15, 16, 18, 21, 23, 24, 26) and
signal ground pins 14 and 25 stay disconnected on Mini. Pins 8/10 are reserved
for UART and 27/28 for ID EEPROM. Pins 2/4 are unused 5 V power pins; pins 19,
22 and 29 are unused GPIOs and pin 30 is an unused ground. Changing a motor's
`inverted` value changes its direction without changing this wiring.
