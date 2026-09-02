# Mecanum robot sample

This folder is a complete browser-deployable Python robot project:

- `hardware.py` owns the eight motor GPIOs, inversion, PWM/deadtime/watchdog,
  and PCA9685 setup;
- `robot.py` exposes the required `create_drive(module)` entry point; and
- `mecanum.py` contains the wheel mixing and channel mapping.

Download it from the Driver Station, unzip it, rename the folder, edit it in
any local editor, then choose that whole folder in **Code → Deploy robot
folder**. MotionModule validates it, backs up a same-named project, activates
it, and restarts.

The first four motor channels are:

| Wheel | Channel |
| --- | ---: |
| Front left | 1 |
| Rear left | 2 |
| Front right | 3 |
| Rear right | 4 |

If one wheel runs backward, change only that channel's `inverted` value in
`hardware.py`. Do not change the rotation formula to compensate for one
reversed motor.

After deployment, use W/S to move, A/D to strafe, Q/E to rotate, and Space to
stop. Enable browser drive deliberately and start with the speed limit low.
The dashboard refreshes the 500 ms hardware watchdog while controls are active.

Extra devices can use the remaining channels:

```python
intake = module.motor(5)
intake.set(0.35)
intake.stop()

arm = module.servo(channel=0, board=0)
arm.set_angle(90)
arm.release()
```

Use Debug's generic Driver 1A–4B pinout and raised-wheel bench tests before
testing this robot-specific wheel assignment.
