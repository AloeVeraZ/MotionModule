"""Standard four-wheel mecanum kinematics.

Positive forward moves toward the front of the robot, positive strafe moves
right, and positive rotate turns counter-clockwise. Motor electrical polarity
belongs in this project's hardware.py, not in this mixer.
"""

from __future__ import annotations

import math


WHEEL_CHANNELS = {
    "front_left": 1,
    "rear_left": 2,
    "front_right": 3,
    "rear_right": 4,
}


def mix(forward: float, strafe: float, rotate: float) -> dict[str, float]:
    values = (forward, strafe, rotate)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        raise ValueError("Drive commands must be numbers")
    if any(not math.isfinite(float(value)) for value in values):
        raise ValueError("Drive commands must be finite")
    forward, strafe, rotate = (
        max(-1.0, min(1.0, float(value))) for value in values
    )
    wheels = {
        "front_left": forward + strafe + rotate,
        "rear_left": forward - strafe + rotate,
        "front_right": forward - strafe - rotate,
        "rear_right": forward + strafe - rotate,
    }
    scale = max(1.0, *(abs(value) for value in wheels.values()))
    return {name: value / scale for name, value in wheels.items()}


class MecanumDrive:
    def __init__(self, module, channels: dict[str, int] | None = None) -> None:
        self.module = module
        self.channels = channels or WHEEL_CHANNELS

    def drive(self, forward: float, strafe: float, rotate: float, speed: float = 0.5) -> dict:
        if isinstance(speed, bool) or not isinstance(speed, (int, float)):
            raise ValueError("Speed must be a number")
        speed = float(speed)
        if not math.isfinite(speed):
            raise ValueError("Speed must be finite")
        speed = max(0.0, min(1.0, speed))
        wheels = mix(forward, strafe, rotate)
        outputs = {self.channels[name]: value * speed for name, value in wheels.items()}
        self.module.set_motors(outputs)
        return {"wheels": wheels, "outputs": outputs, "speed": speed}

    def stop(self) -> None:
        self.module.set_motors({channel: 0 for channel in self.channels.values()})
