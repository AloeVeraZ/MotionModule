# Mecanum sample robot

Five small files make the complete sample. Only one is required.

| File | What it does | Required? |
| --- | --- | --- |
| `robot.py` | Turns drive commands into wheel power | Yes |
| `hardware.py` | Names each motor and servo, and holds the pins | No — delete it to use the built-in names |
| `sensors.py` | Every sensor, read by the Arduino GIGA, by name | No — without a GIGA, remove its import from `robot.py` |
| `autonomous.py` | The routine the robot runs by itself | No — delete it and there is no autonomous mode |
| `dashboard.py` | Driver Station cameras, sensors, and key layout | No — delete it without affecting Drive |

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

The base driver map already has inverted polarity for output A (`front_left`
and `front_right`). This Mecanum sample additionally sets `inverted` on motor
2 / Driver 1B (`rear_left`) and motor 4 / Driver 2B (`rear_right`). Their pins
do not move: positive power uses the other input in each existing IN3/IN4
pair. Never change the math in `mix()` to cancel out one motor.

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

After deploying, tick the enable box on the **Drive** page, then use W/S to
drive, A/D to strafe, Q/E to rotate, and Space to stop. Start with the speed
limit low.

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

## Sensors: the Arduino GIGA

`sensors.py` lists everything wired to the Arduino GIGA R1 WiFi: a BNO055
9-axis IMU, an ISM330DHCX 6-axis IMU, an arm potentiometer on A0, and an intake
beam break on D22. The GIGA reads them and passes the numbers to the Pi, which
does the rest. `robot.py` imports this file, and the drive object carries it as
`drive.sensors`, which `autonomous.py` and `dashboard.py` both use.

1. Plug the GIGA into a Pi USB port and install its firmware from **Debug →
   Checks & logs → Install firmware**, or run `motionmodule giga flash`. No
   Arduino IDE is needed, and this is done once.
2. Wire the IMUs to 3.3V, GND, SDA 20 and SCL 21, as `sensors.py` describes.
3. Delete any IMU or pin in `sensors.py` that this robot does not have.

With an IMU streaming, **Zero heading** and **Calibrate gyro** appear among the
Drive page's controls, and autonomous turns a measured quarter turn instead of
turning for a fixed time. Headings count up turning left, like `rotate`.

## Full Driver Station: cameras, IMU, and sensors

`dashboard.py` is discovered automatically when it is beside `robot.py`.
The compact **Drive** page remains a drivetrain debugger. Press **Open full
Driver Station** for the independent operator console. The sample shows two
offline camera placeholders, the first IMU in `sensors.py` on the heading dial,
and every GIGA pin and IMU in the USB controller card. Add browser-readable
stream URLs for a C920 or C270.

`driver_bindings()` in the same file decides which keys the Driver Station
listens for. The sample keeps the usual W/S, A/D, Q/E and space; return only
what you want to move. This is the robot's own layout and is unrelated to the
**Drive** page, which each browser remaps for itself.

The camera selector shows the front feed, rear feed, or both square viewports.

Before putting the robot on the floor, use **Debug → Motor bench test** with
every wheel off the ground and confirm each named motor turns the way you
expect.
