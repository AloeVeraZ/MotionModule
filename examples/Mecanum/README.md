# Mecanum sample robot

Four small files make the complete sample. Only one is required.

| File | What it does | Required? |
| --- | --- | --- |
| `robot.py` | Turns drive commands into wheel power | Yes |
| `hardware.py` | Names each motor and servo, and holds the pins | No — delete it to use the built-in names |
| `dashboard.py` | Declares full Driver Station cameras, Pi inputs, and GIGA inputs | No — delete it without affecting Drive |
| `giga_sensor_bridge.ino` | Reusable GIGA R1 USB sensor firmware | No — flash it only when using the GIGA |

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

## Full Driver Station: cameras, IMU, and sensors

`dashboard.py` is discovered automatically when it is beside `robot.py`.
The compact **Drive** page remains a drivetrain debugger. Press **Open full
Driver Station** for the independent operator console. The sample declares two
offline camera placeholders, an offline IMU, an unused Pi GPIO input, and an
Arduino GIGA R1 bridge. Add browser-readable stream URLs for a C920 or C270,
then replace the placeholder reads with live hardware values.

The camera selector shows the front feed, rear feed, or both square viewports.
Pi digital readings and USB-controller readings are separate. Flash
`giga_sensor_bridge.ino` to the GIGA once; the Pi detects USB `2341:0266`, and
the `GigaPin` entries in `dashboard.py` configure which analog or digital pins
the reusable sketch streams.

Before putting the robot on the floor, use **Debug → Motor bench test** with
every wheel off the ground and confirm each named motor turns the way you
expect.
