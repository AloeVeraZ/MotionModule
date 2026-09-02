# Coding a MotionModule robot

Robot code is a normal local Python folder. You may use any text editor; the
only deployment tool is the robot's browser Driver Station.

## Start from the sample

1. Open `http://motionmodule.local/code` or the robot's IP in Chrome or Edge.
2. Press **Download Mecanum sample**.
3. Unzip it and rename the `Mecanum` folder for the new robot.
4. Edit that folder locally.
5. Return to Code, choose the whole folder, confirm, and press **Deploy and
   run**.

The same upload works on the saved Wi-Fi, Ethernet, and the direct MotionModule
hotspot. The local folder cannot move hardware. Only the validated copy sent to
the Pi runs.

## Required files

```text
MyRobot/
├── robot.py       # creates the browser drive controller
├── hardware.py    # pins, inversion, PWM, watchdog, servo boards
└── helpers.py     # any other Python files you want
```

`hardware.py` must contain a single literal dictionary assignment:

```python
HARDWARE = {
    "module": {"pwm_hz": 1000, "deadtime_ms": 15, "watchdog_ms": 500},
    "motors": {
        1: {
            "name": "front_left",
            "forward_gpio": 12,
            "reverse_gpio": 6,
            "inverted": True,
        },
    },
    "servos": {
        "enabled": True,
        "i2c_bus": 1,
        "frequency_hz": 50,
        "addresses": [0x40],
        "minimum_pulse_us": 500,
        "maximum_pulse_us": 2500,
    },
}
```

It may have a docstring, but no imports, calls, calculations, or other
statements. Every browser-deployed project must include this file. Debug reads
the active project's configuration to draw the generic wiring map.

`robot.py` defines the dashboard hook:

```python
from my_drive import MyDrive


def create_drive(module):
    return MyDrive(module)
```

The returned object implements:

```python
drive(forward, strafe, rotate, speed) -> dict
stop() -> None
```

Avoid permanent loops and hardware movement at module scope. MotionModule must
be able to import the project before it can serve the dashboard.

## Motor API

```python
motor = module.motor(5)
motor.set(0.25)   # -1.0 to +1.0
motor.stop()

module.set_motors({1: 0.4, 2: 0.4, 3: -0.4, 4: -0.4})
module.stop_all()
```

The controller clamps power, applies the `inverted` value from `hardware.py`,
inserts a coast interval before reversing, and stops stale output at the
watchdog deadline. A control routine must resend nonzero values faster than
that deadline.

## Servo API

```python
arm = module.servo(channel=0, board=0)
arm.set_angle(90)
arm.set_pulse_us(1500)
arm.release()
```

Each configured PCA9685 has channels 0–15. Verify the exact servo's voltage,
pulse range, mode, and mechanical clearance before commanding it. Use Debug's
guarded Servo Pulse Test for first movement.

## Add mechanisms and sensors

Put robot-specific code in additional `.py` files inside the same folder:

```python
# mechanisms.py
class Intake:
    def __init__(self, module, channel=5):
        self.motor = module.motor(channel)

    def run(self, power=0.35):
        self.motor.set(power)

    def stop(self):
        self.motor.stop()
```

Then import it with `from mechanisms import Intake`. USB or serial libraries
needed by a project must already be installed in the MotionModule runtime;
Debug's USB list only discovers attached devices and does not install drivers.

## What deployment validates

Before changing the active project, the Pi checks:

- one folder with a safe 1–64 character project name;
- `robot.py` and `hardware.py` at the top level;
- only `.py`, `.md`, and `.txt` files, up to 250 files and 8 MiB total;
- valid syntax in every Python file;
- a synchronous top-level `create_drive(module)` function;
- literal-only hardware data, valid GPIOs, unique motor pins, allowed I2C
  addresses, pulse limits, and watchdog limits.

It then stops outputs, backs up an existing same-named folder, replaces it,
switches `~/MotionModule/active`, and restarts. If the new project later fails
while importing a dependency, open Debug's service log and correct the local
folder before deploying again.

## Manual testing

The Code page's W/A/S/D/Q/E controls call your `drive()` method. Keyboard drive
works only while its deliberate-enable box is selected. Releasing keys, Space,
STOP, leaving the page, or losing communications produces a stop; the hardware
watchdog is the final backstop.

Keep a physical power cutoff in reach. First verify every raw output using
Debug with the chassis raised, then test the project's drive mapping slowly.
