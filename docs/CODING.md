# Coding robots on MotionModule

## Use VS Code

VS Code is the single supported editor, with two ways to reach the robot:

- **Remote - SSH:** connect to `YOUR_PI_USER@motionmodule.local`, open
  `~/MotionModule/robots/PROJECT_NAME`, edit the Pi copy, and run
  `motionmodule restart` in the VS Code terminal.
- **Local then push:** open the MotionModule repository locally in VS Code,
  create a project folder containing `robot.py`, and push it over SSH. Local
  files do not execute on the robot until the push finishes successfully.

For the local workflow, copy `examples/Mecanum` to a folder such as
`robots/MyRobot`, edit it, then choose **Terminal → Run Task → MotionModule:
Push robot project**. VS Code asks for the folder and SSH target. The direct
terminal equivalent is:

```bash
python tools/push_robot.py robots/MyRobot --host YOUR_PI_USER@motionmodule.local
```

The helper requires Python plus the standard `ssh` and `scp` commands on the
development computer. It archives the selected folder without Git metadata,
virtual environments, build output, or caches. The Pi rejects unsafe archive
paths and links, checks `robot.py` and every other Python file for syntax,
backs up an existing project to `~/MotionModule/backups`, installs the new
copy, makes it active, and restarts the service. A failed validation leaves the
currently installed project unchanged.

The system dashboard loads exactly one active robot project's drive hook:

```text
~/MotionModule/active/robot.py
```

The starter file defines:

```python
from mecanum import MecanumDrive

def create_drive(module):
    return MecanumDrive(module)
```

The returned object implements `drive(forward, strafe, rotate, speed)` and
`stop()`. `module` is the hardware controller. MotionModule owns the web server,
network setup, and cleanup, so runtime updates do not overwrite the student
folder. Existing projects with the original `MecanumDrive` class remain
compatible even when they do not yet define `create_drive`.

## Robot project folders

`Mecanum` is one example, not a required drivetrain. Create a project folder
under `~/MotionModule/robots` and give it a `robot.py`:

```text
~/MotionModule/
├── active -> robots/Mecanum/
└── robots/
    ├── Mecanum/robot.py
    ├── Swerve/robot.py
    └── WalkingRobot/robot.py
```

The drive object returned by `create_drive(module)` can implement Mecanum,
swerve, tank, walking, or another mechanism. It only needs `drive(...)` and
`stop()` methods compatible with the dashboard controls. List and switch
projects with:

```bash
motionmodule project list
motionmodule project Swerve
```

The switch restarts the service. Hardware configuration remains shared at
`~/.config/motionmodule/config.toml`; project code remains independent.

## Motors

Channels are 1 through 8:

```python
intake = module.motor(5)
intake.set(0.30)   # -1.0 to +1.0
intake.stop()
```

For coordinated motion, update channels together. This gives every reversing
channel one shared coast/deadtime interval:

```python
module.set_motors({1: 0.4, 2: 0.4, 3: 0.4, 4: 0.4})
```

Any nonzero motor output arms the watchdog. Refresh with another motor command
or `module.feed_watchdog()` within 500 ms. A stale controller stops all motors.

## Servos

PCA9685 boards count from zero. Each board has channels 0 through 15:

```python
claw = module.servo(channel=0, board=0)
claw.set_angle(30)
claw.set_angle(110)
claw.release()
```

`set_angle()` is the generic 0–180° API. For a calibrated servo profile, the
dashboard maps its logical position or continuous-rotation speed to a pulse and
the low-level project API can send that pulse directly:

```python
claw.set_pulse_us(1500)  # midpoint / neutral for the configured servo
```

Direct pulses are restricted to the configured `minimum_pulse_us` and
`maximum_pulse_us` safety envelope. The commissioning dashboard includes
goBILDA 300°, goBILDA 5-turn/1800°, goBILDA continuous, generic 180°, and
generic 360° profiles. A PCA9685 board has channels 0–15; channel 16 does not
exist.

`release()` turns that PWM output fully off; it does not physically move the
servo to a safe pose first. Code the safe pose for the actual mechanism, wait
for motion, then release if the mechanism should not hold torque.

## Mecanum math and the turning fix

The example treats physical/electrical motor direction and chassis kinematics as
separate layers. The standard normalized wheel equations are:

```text
front_left  = forward + strafe + rotate
rear_left   = forward - strafe + rotate
front_right = forward - strafe - rotate
rear_right  = forward + strafe - rotate
```

A pure rotation therefore drives both left wheels together and both right
wheels in the opposite direction. The earlier City Tech version mixed the
front wheels against the rear wheels and tried to account for installed motor
orientation inside the math; that can produce diagonal/translation behavior
instead of a center turn. The default config now marks the installed first four
motors as inverted, so the mixer remains conventional and testable.

If a wheel is wrong, calibrate its `inverted` setting. If the robot turns the
opposite named direction but otherwise rotates correctly, swap the Q/E mapping
or invert the `rotate` command once at the control boundary.

## Running without hardware

On any development computer:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

Non-Pi computers automatically simulate GPIO and PCA9685 state. On a Pi, set
`MOTIONMODULE_MOCK=1` before a manual run to avoid touching hardware.
