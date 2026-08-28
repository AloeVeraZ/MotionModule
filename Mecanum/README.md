# Mecanum example

This is the student-editable robot project. `robot.py` hosts the local browser
driver station, while `mecanum.py` contains the wheel math. The installer runs
this folder automatically as `motionmodule.service`.

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

Open `http://motionmodule.local:8080` after installation. Use W/S to move,
A/D to strafe, Q/E to rotate, and Space or Escape to stop. The page refreshes
the 500 ms hardware watchdog every 80 ms while it is open. The gear button
shows the Pi's current IP and provides Wi-Fi scan, preferred-network, and robot
hotspot controls. Opening it stops all motors before any network change.

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
