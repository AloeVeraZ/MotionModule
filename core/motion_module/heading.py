"""Heading control from the IMU: hold a direction, turn to one, snap by 90°.

HeadingController supplies TeleOp's proportional and derivative loop:

    error = target - heading, wrapped to -180..180 so it turns the short way
    power = kP * error - kD * turn_rate

kP pushes toward the target; kD, fed by the gyro's measured turn rate, brakes
so the robot does not overshoot. The starting proportional gain is 0.02 per
degree, with damping from the gyro. A turn counts as finished only after the
heading has stayed within the tolerance for a moment, so a robot swinging
through the target does not count.

Autonomous uses TurnPID below, with independent gains and a bounded integral
term to overcome friction near a marker.

Angles are degrees and count up turning left (counter-clockwise), the same
way a positive ``rotate`` turns, so a positive power turns left. Powers here
are real motor power (0 to 1), before any speed limit.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field


def wrap180(degrees: float) -> float:
    """The same direction written between -180 and 180."""

    return (float(degrees) + 180.0) % 360.0 - 180.0


def nearest_step(heading: float, step: float = 90.0) -> float:
    """The multiple of ``step`` closest to ``heading``, e.g. 83° -> 90°."""

    return wrap180(round(float(heading) / step) * step)


@dataclass
class HeadingController:
    """Turn power toward a target heading: proportional plus damping.

    kp               power per degree of error
    kd               power per degree/second of turning, as a brake
    max_power        the most turn power it ever asks for
    min_turn_power   the least power that still turns the robot on the spot;
                     used only when turning in place, so the last few degrees
                     do not stall on friction. Raise it if turns stop short.
    tolerance        degrees from the target that count as there
    settle_seconds   how long the heading must stay there to be finished
    """

    kp: float = 0.02
    kd: float = 0.001
    max_power: float = 0.5
    min_turn_power: float = 0.2
    tolerance: float = 2.0
    settle_seconds: float = 0.1

    def error(self, target: float, heading: float) -> float:
        return wrap180(target - heading)

    def power(self, target: float, heading: float, rate: float | None = None, *, in_place: bool = True) -> float:
        """Turn power, positive to turn left. ``rate`` is degrees/second, left positive."""

        error = self.error(target, heading)
        rate = rate or 0.0
        if in_place and abs(error) <= self.tolerance:
            # On target: only brake whatever turn is left, so it does not coast out.
            power = -self.kd * rate
        else:
            power = self.kp * error - self.kd * rate
            # Friction can hold a stopped robot against a small push, so a
            # stopped robot gets at least min_turn_power toward the target. A
            # robot already turning needs no boost, and a brake is never boosted.
            stopped = abs(rate) < self.STOPPED_DPS
            if in_place and stopped and power * error > 0 and abs(power) < self.min_turn_power:
                power = math.copysign(self.min_turn_power, power)
        return max(-self.max_power, min(self.max_power, power))

    STOPPED_DPS = 15.0   # turning slower than this counts as stopped


class Settle:
    """True once the heading has stayed within tolerance for settle_seconds."""

    def __init__(self, controller: HeadingController) -> None:
        self.controller = controller
        self._since: float | None = None

    def update(self, target: float, heading: float, now: float) -> bool:
        if abs(self.controller.error(target, heading)) > self.controller.tolerance:
            self._since = None
            return False
        if self._since is None:
            self._since = now
        return now - self._since >= self.controller.settle_seconds


@dataclass
class TurnPID(HeadingController):
    """Stateful PID for stationary autonomous turns; reset for each target.

    Derivative follows measured heading movement across the angle wrap, rather
    than a target change or a biased gyro-rate reading. Integral acts only near
    the target, is bounded in motor power, and clears on arrival or crossing.
    TeleOp continues using HeadingController independently.
    """

    kp: float = 0.018
    ki: float = 0.006
    kd: float = 0.004
    max_power: float = 0.4
    tolerance: float = 3.0
    settle_seconds: float = 0.3
    integral_window: float = 20.0
    integral_power_limit: float = 0.20
    derivative_seconds: float = 0.06
    STOPPED_DPS = 8.0

    rate: float = field(default=0.0, init=False)
    _integral: float = field(default=0.0, init=False)
    _last_heading: float | None = field(default=None, init=False)
    _last_time: float | None = field(default=None, init=False)
    _last_error: float | None = field(default=None, init=False)

    def reset(self) -> None:
        self.rate = self._integral = 0.0
        self._last_heading = self._last_time = self._last_error = None

    def update(self, target: float, heading: float, now: float, *, limit: float | None = None) -> float:
        """Return actual signed motor power, including reverse correction."""

        error = self.error(target, heading)
        dt = 0.0 if self._last_time is None else max(0.0, now - self._last_time)
        if dt > 0 and self._last_heading is not None:
            measured_rate = wrap180(heading - self._last_heading) / dt
            alpha = dt / (self.derivative_seconds + dt)
            self.rate += alpha * (measured_rate - self.rate)
        crossed = self._last_error is not None and self._last_error * error < 0
        self._last_heading, self._last_time, self._last_error = heading, now, error
        limit = self.max_power if limit is None else min(self.max_power, limit)

        on_target = abs(error) <= self.tolerance
        if on_target or crossed or abs(error) > self.integral_window:
            self._integral = 0.0
        elif self.ki > 0 and dt > 0:
            bound = self.integral_power_limit / self.ki
            candidate = max(-bound, min(bound, self._integral + error * min(dt, 0.1)))
            raw = self.kp * error + self.ki * candidate - self.kd * self.rate
            # Don't wind up while pushing into the power cap; allow unwinding.
            if abs(raw) <= limit or raw * error <= 0:
                self._integral = candidate

        if on_target:
            # Let a stationary robot rest inside the band, brake a fast crossing.
            power = 0.0 if abs(self.rate) <= self.STOPPED_DPS else -self.kd * self.rate
        else:
            power = self.kp * error + self.ki * self._integral - self.kd * self.rate
            if abs(self.rate) < self.STOPPED_DPS and power * error > 0:
                power = math.copysign(max(abs(power), self.min_turn_power), power)
        return max(-limit, min(limit, power))


class HeadingHold:
    """Driver assist for TeleOp: hold the heading while driving, snap-turn by 90°.

    Call :meth:`update` with every drive command. While the driver turns, the
    driver is in charge. Shortly after they let go, the direction the robot
    then faces is locked, and while it drives or strafes a small turn is added
    to keep it there, so it goes straight instead of drifting. Standing still,
    it does nothing, so a robot at rest never twitches.

    :meth:`snap` turns to the next multiple of 90° (pressed again mid-turn, the
    next one after that). Moving the turning stick cancels a snap.

    If the heading ever runs away from the correction - the sign of the turn
    is wrong, or the robot is stuck - holding switches itself off and says why
    in :attr:`message`, rather than spinning the robot.
    """

    def __init__(
        self,
        controller: HeadingController | None = None,
        *,
        lock_delay: float = 0.25,
        deadband: float = 0.05,
        runaway_degrees: float = 45.0,
        snap_timeout: float = 3.0,
        clock=time.monotonic,
    ) -> None:
        self.controller = controller or HeadingController()
        self.lock_delay = lock_delay
        self.deadband = deadband
        self.runaway_degrees = runaway_degrees
        self.snap_timeout = snap_timeout
        self._clock = clock
        self.enabled = True
        self.target: float | None = None
        self.snapping = False
        self.message = ""
        self._last_manual = -math.inf
        self._snap_started = 0.0
        self._snap_error = 0.0
        self._settle = Settle(self.controller)

    # -- driver actions ------------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        self.cancel()
        self.message = "" if self.enabled else "Heading hold is off."

    def cancel(self) -> None:
        """Forget the locked heading and any snap in progress."""

        self.target = None
        self.snapping = False

    def snap(self, heading: float | None, direction: int) -> float | None:
        """Start a 90° turn: +1 left, -1 right. Returns the new target."""

        if heading is None:
            self.message = "Snap turn needs the IMU: it is not ready."
            return None
        base = self.target if self.snapping and self.target is not None else nearest_step(heading)
        self.target = wrap180(base + 90.0 * (1 if direction > 0 else -1))
        self.snapping = True
        self._snap_started = self._clock()
        self._snap_error = abs(self.controller.error(self.target, heading))
        self._settle = Settle(self.controller)
        self.message = ""
        return self.target

    # -- every drive command ---------------------------------------------------

    def update(self, heading: float | None, rate: float | None, forward: float, strafe: float, rotate: float) -> float | None:
        """Turn power to use instead of the driver's, or None to use theirs."""

        now = self._clock()
        if heading is None:
            self.cancel()
            return None
        if abs(rotate) > self.deadband:
            self.cancel()
            self._last_manual = now
            return None
        driving = abs(forward) > self.deadband or abs(strafe) > self.deadband
        if self.snapping:
            return self._snap(heading, rate, driving, now)
        if not self.enabled:
            return None
        if self.target is None:
            # Let a turn the driver just finished coast out before locking,
            # so the robot is not yanked back to where the stick was released.
            if now - self._last_manual < self.lock_delay or abs(rate or 0.0) > 30.0:
                return None
            self.target = heading
        if not driving:
            return None
        if abs(self.controller.error(self.target, heading)) > self.runaway_degrees:
            self.enabled = False
            self.cancel()
            self.message = (
                "Heading hold switched itself off: the robot turned away from its "
                "correction. Check that the heading goes up on a left turn, then turn it back on."
            )
            return None
        return self.controller.power(self.target, heading, rate, in_place=False)

    def _snap(self, heading: float, rate: float | None, driving: bool, now: float) -> float:
        error = abs(self.controller.error(self.target, heading))
        if error > self._snap_error + self.runaway_degrees:
            self.cancel()
            self.message = "Snap turn stopped: the robot turned the wrong way. Check that the heading goes up on a left turn."
            return 0.0
        if self._settle.update(self.target, heading, now):
            self.snapping = False   # arrived: keep the target as the held heading
            return 0.0
        if now - self._snap_started > self.snap_timeout:
            self.snapping = False
            self.message = f"Snap turn stopped {error:.0f}° short. Raise min_turn_power if turns stall."
            return 0.0
        return self.controller.power(self.target, heading, rate, in_place=not driving)

    def describe(self) -> str:
        if self.message:
            return self.message
        if self.snapping and self.target is not None:
            return f"Turning to {self.target:.0f}°."
        if not self.enabled:
            return "Heading hold is off."
        if self.target is not None:
            return f"Holding {self.target:.0f}°."
        return "Heading hold on."
