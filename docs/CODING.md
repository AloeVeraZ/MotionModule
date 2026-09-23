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
├── test.py        # optional: Debug Drive Test motor/servo mapping (Mecanum by default)
├── hardware.py    # optional: your own names, pins, inversion, servo boards
├── sensors.py     # BNO055 wired directly to the Pi
├── autonomous.py  # optional: the routine the robot runs by itself
├── dashboard.py   # optional: Driver Station cameras, sensors, keys, sticks
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

### Optional Debug Drive Test mapping

**Debug → Drive Test** loads `MyRobot/test.py`, next to `robot.py`. The sample
download includes this default file:

```python
from motion_module.mecanum import MecanumTestDrive


def create_test(module):
    return MecanumTestDrive(module)
```

No `test.py`? The same confirmed Mecanum test remains available. A present but
broken file disables Drive Test and displays its error; it never silently
substitutes another drive. After editing locally, deploy the whole robot folder
through Code to reload it. Existing customized projects are not overwritten by
an update; copy the sample's `test.py` into your folder when you want to customize it.

To test another drivetrain, return your own object with
`drive(forward, strafe, rotate, speed)` and `stop()`. The keys stay fixed:
W/S sends positive/negative `forward`, D/A positive/negative `strafe`, and Q/E
positive/negative `rotate`. Axes are clamped to −1…1 and speed to 0…1.
Use the supplied `module.set_motors(...)`, `module.motor(...)`, and
`module.servo(...)` APIs to map those inputs to motor/servo outputs; respect
the speed limit and stop on zero inputs. Return a JSON-compatible dictionary
or `None`. Tank code may ignore strafe; swerve code may command steering servos
as well as motors. These are output mappings, not changes to the shipped wiring.

Do not start loops/threads, move outputs while importing/constructing the
object, or open a second MotionModule. Each method must return promptly.
Space/Disable calls `stop()`, then forcibly stops **all** motors and releases
**all** servo pulses, even if your stop method fails. A command error or a
gap longer than the configured watchdog also stops/releases test outputs.
Keep Space as a safety stop, not an actuator command. Releasing servo pulses
does not mechanically hold a loaded mechanism: support it safely before testing.

This file affects only Debug. The full Driver Station still uses `robot.py`
(or its explicitly selected confirmed Mecanum mixer). `dashboard.py` key and
stick layouts and autonomous code do not change Drive Test.

### Optional full Driver Station telemetry

**Debug → Drive Test** uses `test.py` or its Mecanum fallback, not `robot.py`.
**Open Driver Station** in the top navigation opens
`/driver-station`, the separate operator console that does. Put `dashboard.py` beside `robot.py` to add up to two camera feeds,
one gyro/IMU, up to 20 Raspberry Pi readings, and up to 20 readings per USB
sensor controller. MotionModule discovers it automatically; no import in
`robot.py` is required, and deleting the file does not affect driving.

Sensors are set up once, in `sensors.py`, and `robot.py` hands them to the
drive object. `dashboard.py` shows that same object, so the console always
displays what the robot code reads:

```python
from motion_module.telemetry import CameraFeed, TelemetryDashboard


FRONT_STREAM = ""  # e.g. http://motionmodule.local:1181/?action=stream


class MyDashboard(TelemetryDashboard):
    def __init__(self, module, drive):
        self.sensors = drive.sensors

    def cameras(self):
        # Naming one camera, with no URL, is enough - see below. A second
        # one is only ever added the same way, one more CameraFeed:
        #
        #     REAR_STREAM = ""
        #     return [
        #         CameraFeed("Front", FRONT_STREAM, connected=bool(FRONT_STREAM)),
        #         CameraFeed("Rear", REAR_STREAM, connected=bool(REAR_STREAM)),
        #     ]
        return [CameraFeed("Front", FRONT_STREAM, connected=bool(FRONT_STREAM))]

    def imu(self):
        return self.sensors.reading()

    def usb_controllers(self):
        return []  # No additional USB sensors declared


def create_dashboard(module, drive):
    return MyDashboard(module, drive)
```

Camera URLs must be relative browser paths or HTTP/HTTPS streams. The Driver
Station preserves square viewports and lets the operator show either feed or
both. Return live readings quickly from `snapshot()`/the group methods; the
page polls them at 4 Hz. Mark missing hardware `connected=False` so it is shown
as offline rather than as a valid zero.

By default only one camera is coded, and that is deliberate: `cameras()`
naming a camera with no URL, as above, does not leave it a permanent offline
placeholder. MotionModule looks for a USB-connected camera itself and streams
it, JPEG-encoded, matching it to that named slot - "Front" here - with no
external streamer and no more code. A second physical camera, beyond what you
named, still shows up on its own and brings up the Front/Both/Rear toggle,
generically named until you give it a `CameraFeed` of its own the same way;
plugging one in - or back in after it was unplugged - is picked up within a
few seconds either way. A slot that already has its own URL (an external
streamer's) is left exactly as given, and leaving `dashboard.py` out
entirely, or `cameras()` empty, still puts one camera tile up. Streaming a
USB camera this way needs `opencv-python-headless`, which the real Pi
dashboard installs on its own, quietly, the first time it finds a camera
project code did not already wire up an external streamer for - the tile
says so while that install runs, which can take a few minutes the very first
time. Without a network connection for that one-time install, or without a
camera plugged in, the tile stays a clearly labelled offline placeholder
instead of an error, and says what to run by hand
(`pip install opencv-python-headless`) if the automatic install failed. The
operator can also rotate any camera's view from the Driver Station itself, in
the browser, with a slider, a quick-rotate button, or by typing an exact angle
- that is a per-viewer display preference, not something `dashboard.py`
configures.

## Pi-connected BNO055 IMU

The Mecanum setup uses one BNO055 wired directly to the Pi. Follow the
[complete wiring plan](PINOUT.md#optional-gy-bno055-nine-axis-imu): VIN to
physical pin 17, GND to 20, SDA to 11 (GPIO17), SCL to 12 (GPIO18), and AD0
to ground pin 6 for address 0x28. BOOT and REST retain their pull-ups; INT is
left disconnected. The motor and PCA9685 wiring stays as shipped.

Add this under `[all]` in `/boot/firmware/config.txt`, then reboot:

```ini
dtoverlay=i2c-gpio,i2c_gpio_sda=17,i2c_gpio_scl=18
```

The sample's `sensors.py` already opens the IMU through MotionModule:

```python
from motion_module.imu import GigaIMU

# GigaIMU is the shared chip declaration; it does not select an Arduino.
imu = module.local_imu(GigaIMU("bno055", "Main IMU", address=0x28))
heading = imu.heading() if imu is not None else None
```

`module.local_imu()` discovers the independent `i2c-gpio` adapter by name,
creates one `motion_module.pi_imu.LocalIMU` reader, and closes it when the
module shuts down. It returns `None` in simulation or without the overlay;
it never falls back to the servo bus. Enable the overlay and restart after
rebooting. With the bus present but the sensor missing, the reader reports
it offline and retries. `smbus2` is included as a runtime dependency.

`imu.heading()` returns degrees from -180 to 180, increasing as the robot
turns left, or `None` until usable readings arrive. `imu.zero()` sets the
current heading to zero. `imu.reading()` supplies the Driver Station;
`connected`, `calibrated`, `pitch()`, `roll()`, `rate()` and `describe()`
provide status and other readings. The BNO055 handles its own fusion; the
sample does not include the old six-axis gyro calibration control.

The sample shares this single reader between robot.py, autonomous.py and
dashboard.py. Autonomous uses measured turns when heading is available,
and timed turns otherwise. No other sensor is predeclared.

## Optional USB GPIO expansion

Additional sensors beyond the reference robot go through USB, directly or
through an **Arduino GIGA R1 WiFi** used for extra GPIO inputs. This is an
experimental extension, not a requirement for Mecanum; verify it with your
own hardware. The bundled firmware targets GIGA R1 WiFi, not Uno or Mega.

The existing bridge code discovers the GIGA by USB identity, opens its serial
port, sends your pin declarations on connection, and reconnects if unplugged.
It does not discover what is wired to the GPIO pins. Install its firmware
with `motionmodule giga flash`; see [setup](SETUP.md#optional-usb-gpio-expansion).

An opt-in extension can start empty:

```python
from motion_module.sensor_bridge import GigaPin

USB_PINS = []  # Add declarations only for additional inputs you actually wire.
expansion = module.giga(pins=USB_PINS)
# Once you add a declaration, read it by name with expansion.value(name).
# Expose expansion.snapshot() from dashboard.py's usb_controllers() method.
```

A declaration uses `GigaPin(pin, name, kind="digital", pull="none")`.
Digital pins D0-D75 read `True` or `False`; `pull` can be `"none"`, `"up"`
or `"down"`. Analog A0-A7 use `kind="analog"` and read 0-4095; optional
`scale`, `offset`, `unit`, `minimum` and `maximum` describe the reading.
Pins accept at most 3.3 V. `expansion.value(name)` returns `None` when no
fresh reading is available. This API reads inputs; it does not add motor
or servo outputs. Declare all inputs once and share the returned bridge.
MotionModule closes it at shutdown and never opens a physical board in simulation.

Leave the sample's USB controller list empty until you add an extension.
The IMU stays on the Pi; no Arduino IMU wiring is part of the reference setup.

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

The board's OE pin cuts all sixteen outputs at once, in hardware, so it still
works when the I2C bus does not:

```python
module.set_servo_outputs_enabled(False)   # every output off at the board
module.set_servo_outputs_enabled(True)
module.servo_outputs_enabled              # True while the outputs are live
```

`hardware.py` says which pin that is (`servos.output_enable_gpio`, GPIO4 by
default) or `None` if OE is left unconnected — in which case disabling raises
rather than pretending. The board pulls OE low on its own, so the outputs are
enabled whenever the Pi is not driving the pin. It is an enable line, not a
power cutoff.

Releasing servos and disabling them are separate on purpose: the Driver Station
sends a stop every time you leave the page, and cutting OE there would leave the
robot's servos dead after an ordinary navigation.

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

## Autonomous

`autonomous.py` is optional. Without it the Driver Station simply has no
autonomous mode; with it, an **AUTONOMOUS** button appears beside
**TELEOPERATED** and **RUN AUTO** starts the routine.

```python
# autonomous.py
import time


class MyAuto:
    duration_seconds = 15.0     # None for no limit

    def __init__(self, module, drive):
        self.module, self.drive = module, drive

    def run(self, stop):
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            if stop.is_set():
                return
            self.drive.drive(1, 0, 0, speed=0.3)
            time.sleep(0.05)


def create_autonomous(module, drive):
    return MyAuto(module, drive)
```

A routine short enough not to need a class can be a bare
`run(module, stop)` function instead.

Three things are worth knowing:

- **An autonomous step is a loop, not one call and a sleep.** The motor
  watchdog stops the robot when commands stop arriving, so keep sending while
  the step lasts.
- **`stop` is a `threading.Event`.** Check `stop.is_set()` inside every wait and
  return as soon as it is set. Pressing DISABLE, the stop key, STOP, leaving the
  page, or losing the link all set it — and all stop every output immediately,
  whether or not your code has noticed yet.
- **The run is bounded.** `duration_seconds` (30 s by default) cuts off a
  routine that never returns; the page reports it as cut short. Set it to `None`
  to remove the limit, and then only DISABLE ends a routine that loops forever.

While autonomous is running, manual drive commands are refused rather than
queued, so the driver and the routine can never fight over the motors.

## The Driver Station's controls

The competition console's controls belong to the robot, so they come from
`dashboard.py`. A computer drives with the keys, or a game controller when one
is plugged in. A phone or tablet drives with two on-screen sticks instead: the
page shows them on a touch-first device, or as soon as the screen is touched,
and brings the keys back when a bound key is pressed. Every method below is
optional, and each returns only what you want to change.

### Keys

```python
def driver_bindings(self):
    return {"turn_left": "z", "turn_right": "c", "stop": "Escape"}
```

Anything left out keeps its default — W/S drive, A/D strafe, Q/E turn, space
disables and stops. A single character is matched without case; a named key
such as `ArrowUp` or `Escape` is matched as the browser reports it. If you bind
a key another action already owns, that other action is left unassigned rather
than one key meaning two things.

### Game controller and touch sticks

`gamepad_sticks()` says which game-controller stick drives, strafes and turns;
`touch_sticks()` says the same for the on-screen sticks. Both name the same
four axes, `left_x`, `left_y`, `right_x` and `right_y`:

```python
def gamepad_sticks(self):
    # A tank drive: left stick forward and back, right stick turns.
    return {"strafe": None, "deadzone": 0.15, "curve": 2}

def touch_sticks(self):
    # One stick to drive, and Turn left / Turn right buttons to turn.
    return {"rotate": "buttons"}
```

| Key | Default | What it does |
| --- | --- | --- |
| `forward` | `"left_y"` | Pushing this axis up drives forward |
| `strafe` | `"left_x"` | Pushing this axis right strafes right |
| `rotate` | `"right_x"` | Pushing this axis right turns right; the touch sticks also take `"buttons"` |
| `deadzone` | `0.12` controller, `0.1` touch | How far a stick moves, from 0 to 0.5, before it counts |
| `curve` | `1.0` | Above 1, up to 3, gives finer control near the middle |

Put `-` in front of an axis to flip it (`"-left_y"`), or use `None` to switch a
motion off. One axis never moves the robot two ways: if you give a motion an
axis another motion has by default, that other motion is switched off. On the
screen, a stick given two motions moves all the way round and a stick given one
moves only that way, so by default the left stick drives and strafes and the
right stick only goes left and right. Whatever the layout, the numbers reach
`drive()` exactly as the keys' do, from -1 to 1.

A touched stick centres itself under the thumb, so touching down never moves
the robot; dragging does, and lifting the thumb stops it at once. A thumb that
was on a stick when the robot was disabled does nothing until it lifts and
touches again. A held key wins over the sticks, and the sticks over a game
controller.

### Game controller buttons

`gamepad_buttons()` says which buttons trigger an action, as `{button:
action}`:

```python
def gamepad_buttons(self):
    return {"left_bumper": "turn_left", "right_bumper": "turn_right"}
```

The buttons are `a`, `b`, `x`, `y`, `left_bumper`, `right_bumper`,
`left_trigger`, `right_trigger`, `dpad_up`, `dpad_down`, `dpad_left` and
`dpad_right`. The actions are the same six `drive()` directions as
`driver_bindings` (`forward`, `back`, `left`, `right`, `turn_left`,
`turn_right`), plus `stop` and `estop`, either of which disables the robot
the instant the button goes down — the controller's own STOP button. A
button held down drives like a held key, at full speed, and wins over that
motion's stick reading. Return only what you want to change: by default the
D-pad's down button is `stop` and the right trigger is `estop`; give a
button `None` to unbind a default without replacing it.

### Touchscreen panels

A phone or tablet shows only robot control, the sticks and the cameras. Turned
on its side, a phone keeps the sticks under the thumbs in the bottom corners.
`touch_panels()` adds any of the other panels:

```python
def touch_panels(self):
    return ["mechanisms", "imu"]
```

The names are `status` (the four status lights), `mechanisms`, `imu`,
`pi_inputs` and `usb_controllers`. A computer always shows every panel.

None of this changes **Debug → Drive Test**, which keeps fixed W/S, A/D, Q/E
and Space keys. Change its motor/servo mapping in `test.py`, not its keys.

## Manual testing

The shipped Mecanum `robot.py` uses `motion_module.mecanum.mix`, shared with
the default **Debug → Drive Test**, so it includes the same physically confirmed turning
correction. Use that mixer when extending this robot rather than maintaining
another copy of its wheel equations. It returns normalized powers keyed by
channels 1–4; motor polarity remains in `hardware.py`.

The Driver Station's **Use confirmed Mecanum mixer** selects that same built-in
movement for manual commands without editing the project's files. It defaults
on for a project named `Mecanum`, off for other projects. Uncheck it to call
your own drive method. Changing it disables and stops outputs, requiring a
fresh enable. Project controls, telemetry, and autonomous routines still run
their own code; this selector only changes the keyboard/gamepad movement path.

With that option unchecked, the **Driver Station** calls your `drive()` method, from the keyboard, a
game controller or the touch sticks. All three send the same `forward`, `strafe`
and `rotate` numbers, so code written for one works with the others. Keys and
sticks are laid out in `dashboard.py`; see
[The Driver Station's controls](#the-driver-stations-controls).

Drive works only while its deliberate-enable box is ticked. Releasing keys or
sticks, the stop key, STOP, leaving the page, or losing communications produces a stop, and
a lost connection also disarms the box so you have to re-arm on purpose. The
hardware watchdog is the final backstop.

While armed, the page sends a command on every tick, including zeros. Letting go
of a key therefore reaches `drive()` as `0, 0, 0` on the next frame rather than
waiting for the watchdog, so a tap is a tap. Your `drive()` is called at roughly
12 Hz whether or not anything is moving; keep it cheap and free of blocking
calls.

A drive object may also declare extra buttons and sliders, which appear in the
full Driver Station:

```python
def controls(self):
    return [{"name": "intake", "label": "Intake", "kind": "hold"}]

def control(self, name, value):
    if name == "intake":
        self.module.motor("driver_3a").set(value)
```

Keep a physical power cutoff in reach. First verify every raw output using
Debug with the chassis raised, then test the project's drive mapping slowly.
