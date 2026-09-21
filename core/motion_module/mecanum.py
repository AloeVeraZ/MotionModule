"""The confirmed robot's Mecanum mixer, shared by the test and sample project.

The Debug page's "Mecanum Test" panel posts here instead of to the robot
project, so a four-wheel Mecanum base can be checked before any robot code
exists, and so a bug in that code cannot be mistaken for a wiring fault.

Channels stay FL=1, RL=2, FR=3, RR=4 — the shipped wiring in AGENTS.md. The
active hardware configuration applies each motor's ``inverted`` value once,
inside the controller; this mixer never moves a pin or flips a motor.

Confirmed rotation correction
-----------------------------
The owner physically verified forward, backward, strafe, and rotation after
reversing channels 1 and 4's rotation contributions, without changing their
forward/strafe contributions or global motor polarity. Both the built-in
test and Mecanum sample now call this mixer. This is the confirmed robot's
calibration, not a new general Mecanum formula or a diagnosis of its wiring.
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

# One row per wheel, as (forward, strafe-right, turn-right) signs. Read it
# down a column to get the channel command signs. Forward is +1 for every
# wheel on purpose: it is the direction the robot is known to drive, and the
# other two moves are written as flips of it.
MIX = {
    FRONT_LEFT: (1, 1, -1),  # Confirmed rotation correction; W/S and A/D unchanged.
    REAR_LEFT: (1, -1, 1),
    FRONT_RIGHT: (1, -1, -1),
    REAR_RIGHT: (1, 1, 1),   # Confirmed rotation correction; W/S and A/D unchanged.
}


def clamp(value, low=-1.0, high=1.0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Mecanum commands must be numbers")
    if not math.isfinite(value):
        raise ValueError("Mecanum commands must be finite")
    return max(low, min(high, float(value)))


def mix(forward, strafe, rotate):
    """Normalized channel powers; +strafe is right and +rotate turns left."""

    forward, strafe, rotate = map(clamp, (forward, strafe, rotate))
    moves = (forward, strafe, -rotate)
    wheels = {
        channel: sum(sign * move for sign, move in zip(signs, moves))
        for channel, signs in MIX.items()
    }
    scale = max(1.0, *(abs(power) for power in wheels.values()))
    return {channel: power / scale for channel, power in wheels.items()}


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
        limit = clamp(speed, 0.0, 1.0)
        outputs = {channel: power * limit for channel, power in mix(forward, strafe, rotate).items()}
        self.module.set_motors(outputs)
        return {"outputs": outputs, "speed": limit}

    def stop(self):
        self.module.set_motors({channel: 0.0 for channel, _ in WHEELS})
