# Mecanum sample robot

Two files. That is the whole robot.

| File | What it does | Required? |
| --- | --- | --- |
| `robot.py` | Turns drive commands into wheel power | Yes |
| `hardware.py` | Names each motor and servo, and holds the pins | No — delete it to use the built-in names |

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

After deploying, tick the enable box on the **Code** page, then use W/S to
drive, A/D to strafe, Q/E to rotate, and Space to stop. Start with the speed
limit low.

Before putting the robot on the floor, use **Debug → Motor bench test** with
every wheel off the ground and confirm each named motor turns the way you
expect.
