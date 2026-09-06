"""Mecanum drive sample — the only file you have to write for a robot.

`hardware.py` next to this file names the four wheels. This file turns the
Driver Station's forward / strafe / rotate commands into wheel power.

MotionModule calls `create_drive(module)` once at startup, then calls
`drive(...)` on the object it returns every time a control command arrives.
"""

import math


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
    rotate   positive spins the robot counter-clockwise

    Wheel powers are scaled down together when a combined command would
    exceed full power, so the robot keeps driving in the requested direction.
    """

    forward = clamp(forward)
    strafe = clamp(strafe)
    rotate = clamp(rotate)
    wheels = {
        "front_left": forward + strafe + rotate,
        "rear_left": forward - strafe + rotate,
        "front_right": forward - strafe - rotate,
        "rear_right": forward + strafe - rotate,
    }
    scale = max(1.0, *(abs(power) for power in wheels.values()))
    return {name: power / scale for name, power in wheels.items()}


class MecanumDrive:
    """Drives the four wheels named in hardware.py."""

    def __init__(self, module, wheels=WHEELS):
        self.module = module
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


def create_drive(module):
    """Required entry point. Return anything with drive(...) and stop()."""

    return MecanumDrive(module)


# ---------------------------------------------------------------------------
# Other things you can do with `module`, using the names from hardware.py:
#
#     intake = module.motor("intake")     # motor_5 renamed in hardware.py
#     intake.set(0.35)                    # -1.0 (reverse) to 1.0 (forward)
#     intake.stop()
#
#     claw = module.servo("claw")         # servo_1 renamed in hardware.py
#     claw.set_angle(90)                  # 0-180 degrees
#     claw.release()                      # stop holding a position
#
#     module.stop_all()                   # stop all motors; release servos separately
# ---------------------------------------------------------------------------
