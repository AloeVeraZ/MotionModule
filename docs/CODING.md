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

## What goes in the folder

```text
MyRobot/
├── robot.py       # required: creates the browser drive controller
├── hardware.py    # optional: your own names, pins, inversion, servo boards
├── dashboard.py   # optional: full Driver Station cameras and sensor telemetry
├── giga_sensor_bridge.ino # optional: reusable Arduino GIGA USB firmware
└── helpers.py     # optional: any other Python files you want
```

Only `robot.py` is required. A folder without `hardware.py` runs on the
installed hardware map, whose names describe the hardware position
(`driver_1a`…`driver_4b` for the eight motor outputs, `servo_0`…`servo_15`
for the servo channels). They are listed in **Debug → Wiring**, and the
dashboard shows whatever names the running hardware map defines.

Add `hardware.py` when this robot needs its own names or wiring. Download the
current one from Debug or Code, rename the outputs you use, and keep it next to
`robot.py`. It must contain a single literal dictionary assignment:

```python
HARDWARE = {
    "module": {"pwm_hz": 1000, "deadtime_ms": 15, "watchdog_ms": 500},
    "motors": {
        1: {
            "name": "front_left",
            "forward_gpio": 26,   # physical pin 37
            "reverse_gpio": 19,   # physical pin 35, right next to it
            "inverted": False,
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

It may have a docstring and comments, but no imports, calls, calculations, or
other statements, so MotionModule can check the pins without running the file.
Debug reads whichever configuration is active to draw the wiring map and to
list the names available to your code.

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

### Optional full Driver Station telemetry

The normal **Drive** page is deliberately a drivetrain debugger. Its **Open
full Driver Station** button opens `/driver-station`, a separate operator
console. Put `dashboard.py` beside `robot.py` to add up to two camera feeds,
one gyro/IMU, up to 20 Raspberry Pi readings, and up to 20 readings per USB
sensor controller. MotionModule discovers it automatically; no import in
`robot.py` is required, and deleting the file does not affect driving.

```python
from motion_module.sensor_bridge import GigaPin, GigaR1Bridge
from motion_module.telemetry import CameraFeed, IMUReading, SensorReading, TelemetryDashboard


FRONT_STREAM = ""  # e.g. http://motionmodule.local:1181/?action=stream
REAR_STREAM = ""   # e.g. http://motionmodule.local:1182/?action=stream


class MyDashboard(TelemetryDashboard):
    def __init__(self, module, drive):
        self.module = module
        self.drive = drive
        self.limit = module.digital_input(4, pull="up")
        self.giga = GigaR1Bridge([
            GigaPin("A0", "Arm potentiometer", kind="analog", unit="raw",
                    minimum=0, maximum=4095),
            GigaPin("D22", "Beam break", kind="digital", pull="up"),
        ])

    def cameras(self):
        return [
            CameraFeed("Front", FRONT_STREAM, connected=bool(FRONT_STREAM)),
            CameraFeed("Rear", REAR_STREAM, connected=bool(REAR_STREAM)),
        ]

    def imu(self):
        # Replace this with yaw/pitch/roll/rate values from the installed IMU.
        return IMUReading(name="Robot IMU", connected=False, calibrated=False)

    def pi_inputs(self):
        return [
            SensorReading("Forward limit", self.limit.value, kind="digital",
                          channel="GPIO4 · pin 7"),
        ]

    def usb_controllers(self):
        return [self.giga.snapshot()]

    def close(self):
        self.giga.close()


def create_dashboard(module, drive):
    return MyDashboard(module, drive)
```

Camera URLs must be relative browser paths or HTTP/HTTPS streams. The Driver
Station preserves square viewports and lets the operator show either feed or
both. Return live readings quickly from `snapshot()`/the group methods; the
page polls them at 4 Hz. Mark missing hardware `connected=False` so it is shown
as offline rather than as a valid zero.

`module.digital_input()` accepts only BCM GPIO that remains unused after the
active motor map and MotionModule's I2C, ID, and UART reservations. Raspberry
Pi header GPIO is digital-only; connect analog sensors through an ADC or the
GIGA instead.

For the GIGA, flash the sample `giga_sensor_bridge.ino` once. MotionModule then
finds the board automatically as USB `2341:0266`, opens its CDC serial port,
and sends the `GigaPin` modes above after every reconnect. The board streams
only those configured readings. USB can identify the board, not the physical
sensor attached to a pin, so names, units, ranges, and pin assignments remain
explicit in `dashboard.py`.

## Motor API

Address a motor by its name, or by its channel number from 1 to 8:

```python
motor = module.motor("driver_3a") # module.motor(5) also works
motor.set(0.25)                   # -1.0 to +1.0
motor.stop()

module.set_motors({"driver_1a": 0.4, "driver_1b": 0.4, "driver_2a": -0.4, "driver_2b": -0.4})
module.stop_all()
```

`motor.name` and `motor.channel` tell you which output a handle refers to,
which is useful when printing debug output.

The controller clamps power, applies the `inverted` value from `hardware.py`,
inserts a coast interval before reversing, and stops stale output at the
watchdog deadline. A control routine must resend nonzero values faster than
that deadline.

## Servo API

```python
arm = module.servo("servo_0")     # module.servo(channel=0, board=0) also works
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
    def __init__(self, module, name="driver_3a"):
        self.motor = module.motor(name)

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
- `robot.py` at the top level;
- only `.py`, `.ino`, `.md`, and `.txt` files, up to 250 files and 8 MiB total;
- valid syntax in every Python file;
- a synchronous top-level `create_drive(module)` function;
- a synchronous top-level `create_dashboard(module, drive)` when a named
  `dashboard.py` is present;
- and, when the folder includes `hardware.py`, literal-only data with valid
  GPIOs, unique motor pins, unique names, allowed I2C addresses, pulse limits,
  and watchdog limits.

It then stops outputs, backs up an existing same-named folder, replaces it,
switches `~/MotionModule/active`, and restarts. If the new project later fails
while importing a dependency, open Debug's service log and correct the local
folder before deploying again.

## Manual testing

The **Drive** page calls your `drive()` method, from either the keyboard or a
game controller. Both send the same `forward`, `strafe` and `rotate` numbers, so
code written for one works with the other. Keys are remappable under
**Drive → Controls**.

Drive works only while its deliberate-enable box is ticked. Releasing keys, the
stop key, STOP, leaving the page, or losing communications produces a stop, and
a lost connection also disarms the box so you have to re-arm on purpose. The
hardware watchdog is the final backstop.

While armed, the page sends a command on every tick, including zeros. Letting go
of a key therefore reaches `drive()` as `0, 0, 0` on the next frame rather than
waiting for the watchdog, so a tap is a tap. Your `drive()` is called at roughly
12 Hz whether or not anything is moving; keep it cheap and free of blocking
calls.

A drive object may also declare extra buttons and sliders for that page:

```python
def controls(self):
    return [{"name": "intake", "label": "Intake", "kind": "hold"}]

def control(self, name, value):
    if name == "intake":
        self.module.motor("driver_3a").set(value)
```

Keep a physical power cutoff in reach. First verify every raw output using
Debug with the chassis raised, then test the project's drive mapping slowly.
