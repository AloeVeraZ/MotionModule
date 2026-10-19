# Mecanum sample robot

Five small Python files make the teleop sample. Only one is required.

| File | What it does | Required? |
| --- | --- | --- |
| `robot.py` | Turns drive commands into wheel power | Yes |
| `test.py` | Debug Drive Test motor/servo mapping | No — without it, the same built-in Mecanum test runs |
| `hardware.py` | Names each motor and servo, and holds the pins | No — delete it to use the built-in names |
| `sensors.py` | MPU6500 read directly by the Pi | Included; missing hardware is shown offline |
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

After deploying, open **Driver Station**, choose **Teleoperated**, open
**Choose program folder**, and click `Mecanum` once. Press **Enable**.
W/S drive, A/D strafe, Q/E rotate, and Space stops. The controller's left stick
drives and strafes; its right stick turns. Normal drive is 100%, left trigger
limits power to 50%, and right trigger to 30%. Both held uses 30%. D-pad down
also stops. The console detects controllers without showing a keyboard grid.

`robot.py` defines `KEYBOARD_INPUTS`, `CONTROLLER_STICKS`, `CONTROLLER_BUTTONS`
and `DRIVE_SPEED`. Both keyboard and controller inputs control the same Python
drive code; `dashboard.py` passes these settings to the console. Change the
`stop` binding in `robot.py` to choose another stop key.

On a phone or tablet the keys give way to two on-screen sticks: the left one
drives and strafes all the way round, the right one turns left and right. Lift
your thumbs to stop; the red button disables everything. Turned on its side, a
phone keeps the sticks in the bottom corners, and the page shows only robot
control, the sticks and the cameras.

The sample imports `motion_module.mecanum.mix`, the same confirmed mixer used
by the default **Debug → Drive Test**. Forward, strafe, rotation, and combined commands
therefore have one implementation. `hardware.py` still supplies the names,
locked pins, and per-motor polarity; no extra inversion is applied in `robot.py`.

The installer bundles two independent Mecanum folders: one teleop and one
autonomous. Both use channels 1–4 on MotionModule and MotionModule Mini. The
installed module type controls available spare channels without changing the
wheel wiring.

```text
robots/
  teleop/
    Mecanum/
      robot.py
      hardware.py
      dashboard.py
      sensors.py
      test.py
  autonomous/
    Mecanum/
      robot.py
      autonomous.py
```

Choose Teleoperated and click Mecanum once in the program picker. The selected
folder's name appears in Robot control; Enable runs it. Choose Autonomous to
select the separate Mecanum gyro-turn program. An autonomous program can also
define `run(module, stop)` directly in its own `robot.py`, without a teleop
`create_drive()` factory.

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

## Autonomous programs

The bundled `robots/autonomous/Mecanum/` program turns left to 90°, 180°, 270°
and 360° from its heading at Enable. It uses the Pi MPU6500 and refuses to move
if the IMU is unavailable. Edit its `autonomous.py` plan or add your own folder
under `robots/autonomous/YourProgram/`. Disable stops outputs and signals the
routine to finish. The Autonomous picker shows only autonomous folders.

## Full Driver Station: cameras, IMU, and sensors

`dashboard.py` is discovered automatically when it is beside `robot.py`.
**Debug → Drive Test** uses `test.py`, not this telemetry hook or `robot.py`.
Press **Open Driver Station** for the independent operator
console, which does. The sample declares a front camera and shows the Pi
MPU6500 on the heading dial. Its additional USB sensor list is empty.
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
