# Mecanum example

This is the student-editable robot project. The versioned MotionModule runtime
hosts the browser dashboard, while `robot.py` supplies its drive hook and
`mecanum.py` contains the wheel math. Future installs update the dashboard
without overwriting this folder.

The first four motor channels are:

| Wheel | Channel |
| --- | ---: |
| Front left | 1 |
| Rear left | 2 |
| Front right | 3 |
| Rear right | 4 |

The mixer uses the standard left-versus-right rotation pattern. If a physical
wheel runs backward, edit only that motor's `inverted` setting in
`~/.config/motionmodule/config.toml`, then run `motionmodule restart`. Do not
change the rotation signs to compensate for one reversed motor.

Open `http://motionmodule.local` (or the Pi's IP address) after installation.
Use W/S to move, A/D to strafe, Q/E to rotate, and Space to stop. The dashboard
refreshes the 500 ms hardware watchdog every 80 ms while driving. Its Network
page shows every Pi IP and provides Wi-Fi scan, preferred-network, and robot
hotspot controls. Starting a network change stops all motors first.

After editing either file, run `motionmodule restart`. Older student folders
that contain the original Flask server remain compatible: MotionModule loads
their drive class and ignores the old page server.

To use a servo from your own code:

```python
arm = module.servo(channel=0, board=0)
arm.set_angle(90)
arm.release()
```

To use an extra motor:

```python
intake = module.motor(5)
intake.set(0.35)
intake.stop()
```
