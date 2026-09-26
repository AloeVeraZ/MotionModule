"""Mecanum drive sample — the only file you have to write for a robot.

`hardware.py` next to this file names the four wheels. This file turns the
Driver Station's forward / strafe / rotate commands into wheel power, and
`sensors.py` reads the robot's MPU6500 directly from the Raspberry Pi.

The same three numbers arrive whether someone is using the keyboard or a game
controller, the way an FTC opmode reads one gamepad's sticks:

    forward  left stick Y   (W / S)
    strafe   left stick X   (A / D)
    rotate   right stick X  (Q / E)

so nothing here needs to know which one is driving.

Driving assist, from the IMU (see motion_module/heading.py):
    heading hold   while you drive or strafe without turning, the robot keeps
                   the direction it faces instead of drifting
    snap turns     Z / C (or the controller's bumpers, set in dashboard.py)
                   turn exactly 90° left / right; press again for the next 90°
Both switch off by themselves if the IMU is not ready.

MotionModule calls `create_drive(module)` once at startup, then calls
`drive(...)` on the object it returns every time a control command arrives.
"""

from motion_module.heading import HeadingController, HeadingHold
from motion_module.mecanum import clamp, mix as mix_channels

from sensors import create_sensors  # sensors.py, next to this file


# These names stay in physical wheel order. Motor 2 (rear_left / Driver 1B)
# and motor 4 (rear_right / Driver 2B) reverse their electrical polarity in
# hardware.py, where that pin-level behavior belongs. Movement uses the same
# confirmed mixer as Debug's Mecanum Test, including its rotation correction.
WHEELS = ("front_left", "rear_left", "front_right", "rear_right")

# The heading loop's tuning, shared with autonomous.py. Start here:
#   robot wobbles or overshoots a snap turn   -> lower KP or raise KD
#   corrections feel weak, drift is slow to fix -> raise KP
#   snap turns stop a few degrees short         -> raise MIN_TURN_POWER
HEADING = HeadingController(
    kp=0.02,               # turn power per degree off target
    kd=0.001,              # braking per degree/second of turning
    max_power=0.5,         # the most turn power the assist uses
    min_turn_power=0.2,    # least power that still turns on the spot
    tolerance=2.0,         # degrees that count as on target
    settle_seconds=0.1,    # ...for this long before a turn is finished
)


def mix(forward, strafe, rotate):
    """Give the shared, confirmed channel mix this project's wheel names."""

    powers = mix_channels(forward, strafe, rotate)
    return {name: powers[channel] for channel, name in enumerate(WHEELS, start=1)}


class MecanumDrive:
    """Drives the four wheels named in hardware.py."""

    def __init__(self, module, wheels=WHEELS, sensors=None, heading=HEADING):
        self.module = module
        # autonomous.py and dashboard.py read the sensors from here.
        self.sensors = sensors
        self.heading = heading
        self.assist = HeadingHold(heading)
        self.wheels = tuple(wheels)
        if len(self.wheels) != 4 or len(set(self.wheels)) != 4:
            raise ValueError("Choose four different motors in front-left, rear-left, front-right, rear-right order")

    def drive(self, forward, strafe, rotate, speed=0.5):
        """Called by the Driver Station. `speed` is the 0.0-1.0 power limit.

        Adds the driving assist: heading hold and snap turns. Code that steers
        by itself, like autonomous.py, calls move() instead.
        """

        forward, strafe, rotate = self.steer(forward, strafe, rotate, speed)
        return self.move(forward, strafe, rotate, speed=speed)

    def steer(self, forward, strafe, rotate, speed=0.5):
        """The driving assist: the driver's command with the IMU's turn added.

        The Driver Station calls this too when "Use confirmed Mecanum mixer" is
        ticked, so heading hold and snap turns work with either mixer.
        """

        forward, strafe, rotate = clamp(forward), clamp(strafe), clamp(rotate)
        limit = clamp(speed, 0.0, 1.0)
        if self.sensors is not None:
            turn = self.assist.update(self.sensors.heading(), self.sensors.rate(), forward, strafe, rotate)
            if turn is not None:
                # The assist works in real motor power; rotate is scaled by the limit.
                rotate = clamp(turn / limit) if limit > 0 else 0.0
        return forward, strafe, rotate

    def move(self, forward, strafe, rotate, speed=0.5):
        """Set the wheels exactly as asked, with no assist."""

        limit = clamp(speed, 0.0, 1.0)
        powers = mix(forward, strafe, rotate)
        outputs = {
            name: powers[position] * limit
            for position, name in zip(WHEELS, self.wheels)
        }
        self.module.set_motors(outputs)
        return {"wheels": powers, "outputs": outputs, "speed": limit}

    def stop(self):
        """Called whenever control stops: keys released, page hidden, STOP."""

        self.module.set_motors({name: 0 for name in self.wheels})

    # ---- optional: extra buttons and sliders in the Driver Station ----------

    def controls(self):
        """Describe Driver Station controls. Delete this if you want none."""

        controls = [
            {"name": "spin_test", "label": "Spin in place", "kind": "hold",
             "detail": "Turns at half power for as long as you hold it"},
            {"name": "creep", "label": "Creep forward", "kind": "slider",
             "minimum": -0.3, "maximum": 0.3, "step": 0.05,
             "detail": "Fine positioning without touching the sticks"},
        ]
        if self.sensors is not None:
            controls += [
                {"name": "zero_heading", "label": "Zero IMU", "kind": "button",
                 "detail": "The way the robot faces becomes 0° and its tilt level, until you zero again"},
                {"name": "recalibrate_gyro", "label": "Recalibrate gyro", "kind": "button",
                 "detail": "Keep the robot still for a second; the zero is kept"},
                {"name": "turn_left_90", "label": "Snap left 90°", "kind": "button",
                 "detail": "Turn to the next 90° on the left (Z)"},
                {"name": "turn_right_90", "label": "Snap right 90°", "kind": "button",
                 "detail": "Turn to the next 90° on the right (C)"},
                {"name": "heading_hold", "label": "Heading hold on/off", "kind": "button",
                 "detail": "Keeps the robot straight while driving; on at start-up"},
            ]
        return controls

    def control(self, name, value):
        """Handle one Driver Station control. `value` is a number."""

        if name == "spin_test":
            return self.move(0, 0, 1 if value else 0, speed=0.5)
        if name == "creep":
            return self.move(value, 0, 0, speed=1.0)
        if self.sensors is None:
            raise ValueError(f"Unknown control: {name}")
        if name == "zero_heading":
            if not self.sensors.zero_heading():
                raise ValueError("The IMU is not ready yet; wait until it reads a heading")
            self.assist.cancel()    # the old held heading means something else now
            return {"heading": self.sensors.heading()}
        if name == "recalibrate_gyro":
            self.assist.cancel()
            self.sensors.recalibrate()
            return {"recalibrating": True}
        if name in ("turn_left_90", "turn_right_90"):
            target = self.assist.snap(self.sensors.heading(), 1 if name == "turn_left_90" else -1)
            if target is None:
                raise ValueError(self.assist.message)
            return {"target": target}
        if name == "heading_hold":
            self.assist.set_enabled(not self.assist.enabled)
            return {"heading_hold": self.assist.enabled}
        raise ValueError(f"Unknown control: {name}")


def create_drive(module):
    """Required entry point. Return anything with drive(...) and stop()."""

    return MecanumDrive(module, sensors=create_sensors(module))


# ---------------------------------------------------------------------------
# Other things you can do with `module`, using the names from hardware.py:
#
#     intake = module.motor("intake")     # driver_3a renamed in hardware.py
#     intake.set(0.35)                    # -1.0 (reverse) to 1.0 (forward)
#     intake.stop()
#
#     claw = module.servo("claw")         # servo_0 renamed in hardware.py
#     claw.set_angle(90)                  # 0-180 degrees
#     claw.release()                      # stop holding a position
#
#     module.stop_all()                   # stop all motors; release servos separately
# ---------------------------------------------------------------------------
