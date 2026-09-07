# Mecanum sample robot

Three small files make the complete sample. Only one is required.

| File | What it does | Required? |
| --- | --- | --- |
| `robot.py` | Turns drive commands into wheel power | Yes |
| `hardware.py` | Names each motor and servo, and holds the pins | No — delete it to use the built-in names |
| `dashboard.py` | Declares camera, IMU, and sensor telemetry | No — delete it to run Drive without telemetry |

## Try it

1. Open the robot dashboard, go to **Code**, and press **Download Mecanum sample**.
2. Unzip it and rename the folder to your robot's name.
3. Edit `robot.py` in any editor.
4. Back in **Code**, choose that folder and press **Deploy and run**.

## The wheels

`hardware.py` gives channels 1-4 these names, and `robot.py` uses them:

| Name | Channel | Driver board |
| --- | ---: | --- |
| `front_left` | 1 | Driver 2 · A |
| `rear_left` | 2 | Driver 2 · B |
| `front_right` | 3 | Driver 1 · A |
| `rear_right` | 4 | Driver 1 · B |

If one wheel spins backward, change only that motor's `inverted` value in
`hardware.py`. Never change the math in `mix()` to cancel out one bad motor.

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

## Cameras, IMU, and sensors

`dashboard.py` is discovered automatically when it is beside `robot.py`.
The sample declares two offline camera placeholders, an offline IMU, and
example analog/digital inputs so the complete Driver Station layout is visible
before those devices are installed. Add browser-readable stream URLs for a
C920 or C270, then replace the placeholder reads with live hardware values.

The camera selector shows the front feed, rear feed, or both square viewports.
The sensor tray accepts up to 20 `SensorReading` values whose `kind` is
`"analog"`, `"digital"`, or `"text"`.

Before putting the robot on the floor, use **Debug → Motor bench test** with
every wheel off the ground and confirm each named motor turns the way you
expect.
