"""Mecanum drive sample — the only file you have to write for a robot.

`hardware.py` next to this file names the four wheels. This file turns the
Drive page's forward / strafe / rotate commands into wheel power, and
`sensors.py` gives it the robot's sensors, all read by the Arduino GIGA.

The same three numbers arrive whether someone is using the keyboard or a game
controller, the way an FTC opmode reads one gamepad's sticks:

    forward  left stick Y   (W / S)
    strafe   left stick X   (A / D)
    rotate   right stick X  (Q / E)

so nothing here needs to know which one is driving.

MotionModule calls `create_drive(module)` once at startup, then calls
`drive(...)` on the object it returns every time a control command arrives.
"""

import math

from sensors import create_sensors  # sensors.py, next to this file


WHEELS = ("front_left", "rear_left", "front_right", "rear_right")


def clamp(value, low=-1.0, high=1.0):
    """Keep a number inside a range, and reject anything that is not a number."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Drive commands must be numbers")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Drive commands must be finite")
    return max(low, min(high, value))


def mix(forward, strafe, rotate):
    """Turn three joystick axes into one power value per wheel.

    forward  positive drives toward the front of the robot
    strafe   positive slides the robot to the right
    rotate   positive spins the robot counter-clockwise (a left turn), the
             same direction an IMU heading counts up

    Turning left runs the left wheels backward and the right wheels forward.
    Wheel powers are scaled down together when a combined command would
    exceed full power, so the robot keeps driving in the requested direction.
    """

    forward = clamp(forward)
    strafe = clamp(strafe)
    rotate = clamp(rotate)
    wheels = {
        "front_left": forward + strafe - rotate,
        "rear_left": forward - strafe - rotate,
        "front_right": forward - strafe + rotate,
        "rear_right": forward + strafe + rotate,
    }
    scale = max(1.0, *(abs(power) for power in wheels.values()))
    return {name: power / scale for name, power in wheels.items()}


class MecanumDrive:
    """Drives the four wheels named in hardware.py."""

    def __init__(self, module, wheels=WHEELS, sensors=None):
        self.module = module
        # autonomous.py and dashboard.py read the sensors from here.
        self.sensors = sensors
        self.wheels = tuple(wheels)
        if len(self.wheels) != 4 or len(set(self.wheels)) != 4:
            raise ValueError("Choose four different motors in front-left, rear-left, front-right, rear-right order")

    def drive(self, forward, strafe, rotate, speed=0.5):
        """Called by the Driver Station. `speed` is the 0.0-1.0 power limit."""

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

    # ---- optional: extra buttons and sliders on the Drive page -------------

    def controls(self):
        """Describe controls for the Drive page. Delete this if you want none."""

        controls = [
            {"name": "spin_test", "label": "Spin in place", "kind": "hold",
             "detail": "Turns slowly for as long as you hold it"},
            {"name": "creep", "label": "Creep forward", "kind": "slider",
             "minimum": -0.3, "maximum": 0.3, "step": 0.05,
             "detail": "Fine positioning without touching the sticks"},
        ]
        if self.sensors is not None:
            controls += [
                {"name": "zero_heading", "label": "Zero heading", "kind": "button",
                 "detail": "The way the robot faces now becomes 0°"},
                {"name": "calibrate_gyro", "label": "Calibrate gyro", "kind": "button",
                 "detail": "Measures the 6-axis gyro again; keep the robot still"},
            ]
        return controls

    def control(self, name, value):
        """Handle one control from the Drive page. `value` is a number."""

        if name == "spin_test":
            return self.drive(0, 0, 1 if value else 0, speed=0.2)
        if name == "creep":
            return self.drive(value, 0, 0, speed=1.0)
        if name == "zero_heading" and self.sensors is not None:
            self.sensors.zero_heading()
            return {"heading": self.sensors.heading()}
        if name == "calibrate_gyro" and self.sensors is not None:
            self.sensors.calibrate_gyro()
            return {"calibrating": True}
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
