# Mecanum sample robot

Six small Python files make the complete sample. Only one is required.

| File | What it does | Required? |
| --- | --- | --- |
| `robot.py` | Turns drive commands into wheel power | Yes |
| `test.py` | Debug Drive Test motor/servo mapping | No — without it, the same built-in Mecanum test runs |
| `hardware.py` | Names each motor and servo, and holds the pins | No — delete it to use the built-in names |
| `sensors.py` | MPU9255 read directly by the Pi | Included; missing hardware is shown offline |
| `autonomous.py` | The routine the robot runs by itself | No — delete it and there is no autonomous mode |
| `dashboard.py` | Driver Station cameras, sensors, keys, and sticks | No — delete it without affecting driving |

## Try it

1. Open the robot dashboard, go to **Code**, and press **Download Mecanum sample**.
2. Unzip it and rename the folder to your robot's name.
3. Edit `robot.py` in any editor.
4. Back in **Code**, choose that folder and press **Deploy and run**.

## The wheels

`hardware.py` gives channels 1-4 these names, and `robot.py` uses them:

| Name | Channel | Driver board | Board inputs | Motor terminal |
| --- | ---: | --- | --- | --- |
| `front_left` | 1 | Driver 1 · A | IN1, IN2 | MOTOR_A |
| `rear_left` | 2 | Driver 1 · B | IN3, IN4 | MOTOR_B |
| `front_right` | 3 | Driver 2 · A | IN1, IN2 | MOTOR_A |
| `rear_right` | 4 | Driver 2 · B | IN3, IN4 | MOTOR_B |

This is the reference wiring the sample expects. On the controller plate, with
the Pi on the left and its USB ports at the bottom, Driver 1 sits beside the
USB ports, Driver 2 above it, Driver 3 to the right of Driver 1 and Driver 4
above Driver 3. **Debug -> Wiring guide** shows every wire. Wire the same way
to run the sample unchanged, or change the pins in `hardware.py` to match your
own wiring.

The drivetrain uses normal polarity for motors 1 and 3 and inverted polarity
for motor 2 / Driver 1B (`rear_left`) and motor 4 / Driver 2B (`rear_right`).
Both Test outputs and Drive use this same `hardware.py`; inversion is applied
once, when the runtime writes to the GPIOs. Never add another inversion in
`mix()`.

Older Mecanum projects without a `hardware.py` use the Pi's installed hardware
file instead. An update now gives that project its own copy of those existing
settings with inversion enabled for motors 2 and 4, retaining its motor names,
other motors' polarity, all other settings, and its existing code. The installed
file remains untouched.
An existing project `hardware.py` is preserved unless the entire folder is
recognized as an unmodified shipped sample.

## Add a mechanism

Channels 5-8 and all sixteen servo outputs are free. Rename them in
`hardware.py`, then use those names:

```python
intake = module.motor("intake")
intake.set(0.35)
intake.stop()

claw = module.servo("claw")
claw.set_angle(90)
claw.release()
```

## Driving

After deploying, open **Driver Station**, tick the enable box, then use W/S to
drive, A/D to strafe, Q/E to rotate, and Space to stop. Start with the speed
limit low.

On a phone or tablet the keys give way to two on-screen sticks: the left one
drives and strafes all the way round, the right one turns left and right. Lift
your thumbs to stop; the red button disables everything. Turned on its side, a
phone keeps the sticks in the bottom corners, and the page shows only robot
control, the sticks and the cameras.

The sample imports `motion_module.mecanum.mix`, the same confirmed mixer used
by the default **Debug → Drive Test**. Forward, strafe, rotation, and combined commands
therefore have one implementation. `hardware.py` still supplies the names,
locked pins, and per-motor polarity; no extra inversion is applied in `robot.py`.

For an existing project named `Mecanum`, the full Driver Station also defaults
to **Use confirmed Mecanum mixer**. This lets older preserved `robot.py` files
use the proven movement without being overwritten. Unchecking it uses that
file's own drive method. Sensors and extra controls still come from the project;
autonomous code is not overridden. Changing the selection stops and disables drive.

## Customize Drive Test

`test.py` is loaded automatically beside `robot.py`, only for **Debug → Drive Test**.
It returns the existing confirmed Mecanum test by default. To test tank, swerve,
or other output mappings, replace its `create_test(module)` implementation with
an object exposing `drive(forward, strafe, rotate, speed)` and `stop()`.
Use the supplied module for motor and servo commands. W/S, A/D, Q/E, and Space
stay fixed; only the outputs associated with the inputs change. Space always
stops all motors and releases servos. Do not move hardware during import or
construction, and do not start background loops. Redeploy the folder to reload.
See [the hook contract](../../docs/CODING.md#optional-debug-drive-test-mapping).
The full Driver Station's `robot.py` behavior is independent of this file.

## Autonomous

`autonomous.py` is optional and is found automatically beside `robot.py`. With
it there, the Driver Station's mode switch offers **AUTONOMOUS** next to
**TELEOPERATED**; pick it, tick the safety box, and **RUN AUTO** starts the
routine. The sample drives forward, turns, then strafes, and stops itself.

Every step is a loop that keeps sending drive commands, because the motor
watchdog stops the robot as soon as commands stop arriving. Each loop checks
`stop.is_set()` so DISABLE ends the routine promptly — and MotionModule stops
the outputs immediately either way. `duration_seconds` cuts off a routine that
never returns. While it runs, manual driving is refused, so the driver and the
routine cannot fight over the motors.

## Sensors: the Pi-connected MPU9255

`sensors.py` reads one MPU9255 directly from the Pi, shared by `robot.py`,
`autonomous.py` and `dashboard.py`. Follow [the reference IMU wiring](../../docs/PINOUT.md#optional-mpu9255-nine-axis-imu):
VCC to physical pin 17, GND to 6 and AD0 to 20, SDA to 11 and SCL to 12.
The Pi installer enables the `i2c-gpio` overlay for its next reboot. The module
discovers the bus and MPU9255 address, then closes its reader on shutdown.
Motors and servos keep their Pi wiring.

**Zero heading** sets the current direction to zero. Heading increases turning
left, like `rotate`. Autonomous uses measured turns when the IMU is ready,
and timed turns otherwise. Missing hardware is shown as offline. Keep the
robot still during startup calibration. The Pi uses gyro and accelerometer
readings; compass/magnetometer and DMP are not used. Relative yaw can drift,
so zero before a run. Mount +Y forward and +Z upward.

No extra sensors are declared. An Arduino **GIGA R1 WiFi** can provide optional
USB GPIO inputs for future additions using the existing auto-detection and
bridge API. This experimental feature may need troubleshooting; it is not
required for the Mecanum robot. See [the opt-in API](../../docs/CODING.md#optional-usb-gpio-expansion).

## Full Driver Station: cameras, IMU, and sensors

`dashboard.py` is discovered automatically when it is beside `robot.py`.
**Debug → Drive Test** uses `test.py`, not this telemetry hook or `robot.py`.
Press **Open Driver Station** for the independent operator
console, which does. The sample declares a front camera and shows the Pi
MPU9255 on the heading dial. Its additional USB sensor list is empty.
USB cameras are discovered automatically; an external stream URL is optional.

`driver_bindings()` in the same file decides which keys the Driver Station
listens for. The sample keeps the usual W/S, A/D, Q/E and space; return only
what you want to move. `gamepad_sticks()` and `touch_sticks()` decide which
stick of a game controller, and of the on-screen pair, drives, strafes and
turns, and `touch_panels()` adds panels to a phone's layout. The sample spells
out every default; see [the Driver Station's controls](../../docs/CODING.md#the-driver-stations-controls).
This is the robot's own layout and is unrelated to the **Debug → Drive Test**,
whose keys are fixed.

The camera selector shows the front feed, rear feed, or both square viewports.

Before putting the robot on the floor, use **Debug → Motor bench test** with
every wheel off the ground and confirm each named motor turns the way you
expect.
