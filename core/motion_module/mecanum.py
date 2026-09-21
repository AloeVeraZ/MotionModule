"""Built-in Mecanum bench drive, independent of deployed robot code.

The Drive page's "Test Mecanum" panel posts here instead of to the robot
project, so a four-wheel Mecanum base can be checked before any robot code
exists, and so a bug in that code cannot be mistaken for a wiring fault.

Channels stay FL=1, RL=2, FR=3, RR=4 — the shipped wiring in AGENTS.md. The
active hardware configuration applies each motor's ``inverted`` value once,
inside the controller; this mixer never moves a pin or flips a motor.

Reading the mix
---------------
Every wheel value below is "push the robot forward", after inversion:

    forward  all four the same sign
    strafe   the X-roller diagonal: FL and RR together, FR and RL together
    rotate   by side: both left wheels opposite both right wheels

Those three patterns are what makes a wheel-position mix-up readable from the
robot's behavior. Forward is blind to any channel swap. Strafe survives a
diagonal swap (FL with RR, or FR with RL) because each diagonal already
shares a sign, but it breaks loudly if a side or an axle is swapped. Rotate
is the only one a diagonal swap breaks: the front pair ends up fighting the
rear pair, every axis cancels, and the robot twitches instead of spinning.

So a base that drives and strafes correctly but will not turn in place has
its two diagonal channels crossed somewhere between the driver board and the
wheels. The Drive page's wheel check names which corner each channel really
turns; fix the mix-up at the motor leads, never by renumbering pins here.
"""

import math

from .config import default_config

# Channel numbers are fixed by the shipped wiring, not by the names a robot
# project happens to give these motors.
FRONT_LEFT, REAR_LEFT, FRONT_RIGHT, REAR_RIGHT = 1, 2, 3, 4

WHEELS = (
    (FRONT_LEFT, "Front left"),
    (REAR_LEFT, "Rear left"),
    (FRONT_RIGHT, "Front right"),
    (REAR_RIGHT, "Rear right"),
)


def clamp(value, low=-1.0, high=1.0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Mecanum commands must be numbers")
    if not math.isfinite(value):
        raise ValueError("Mecanum commands must be finite")
    return max(low, min(high, float(value)))


class MecanumTestDrive:
    """Reference X-roller layout; +strafe is right, +rotate turns left."""

    def __init__(self, module):
        self.module = module

    def _check_wiring(self):
        """Refuse a different map rather than silently driving unrelated pins."""

        for expected in default_config().motors[:4]:
            actual = self.module.config.motor(expected.channel)
            if (actual.forward_gpio, actual.reverse_gpio) != (expected.forward_gpio, expected.reverse_gpio):
                raise ValueError("Test Mecanum requires the reference wiring on motor channels 1-4")

    def drive(self, forward, strafe, rotate, speed=0.4):
        self._check_wiring()
        forward, strafe, rotate = map(clamp, (forward, strafe, rotate))
        limit = clamp(speed, 0.0, 1.0)
        wheels = {
            FRONT_LEFT: forward + strafe - rotate,
            REAR_LEFT: forward - strafe - rotate,
            FRONT_RIGHT: forward - strafe + rotate,
            REAR_RIGHT: forward + strafe + rotate,
        }
        scale = max(1.0, *(abs(power) for power in wheels.values()))
        outputs = {channel: power / scale * limit for channel, power in wheels.items()}
        self.module.set_motors(outputs)
        return {"outputs": outputs, "speed": limit}

    def stop(self):
        self.module.set_motors({channel: 0.0 for channel, _ in WHEELS})
