"""Independent Mecanum autonomous routine: four IMU-guided turns.

Choose Autonomous, select Autonomous Driver, then press Enable to run it.

MotionModule calls `create_autonomous(module, drive)` once at startup, then
calls `run(stop)` on the object it returns each time the operator starts
autonomous.

What it does: turn left to 90, 180, 270 and 360 degrees from the starting
heading, then end. Each turn cruises, progressively slows over the last 25
degrees, and latches an even slower recovery rate if it overshoots. Cruise
returns only for the next marker. Reverse as needed and stay within ±3 degrees
at a low measured turn rate for 0.2 seconds before advancing. Crossing a marker is not enough.
It never translates. Change PLAN to make your own. This program has its own
folder and does not import teleop code.

It never zeroes the IMU. Every angle in PLAN counts from the way the robot
faces when Enable is pressed, so line the robot up first.

The robot has no wheel encoders, so a "drive" step goes for a set time, not
a set distance. Without a working IMU the routine does not move at all.

The one rule: check `stop.is_set()` inside every wait and return as soon as it
is true. The operator pressing DISABLE sets that flag, and MotionModule stops
every output immediately whether or not this code notices, but a routine that
returns promptly is a routine you can trust.
"""

import math
import time

from motion_module.heading import HeadingController, Settle, TurnPID, wrap180


# Each step is one of:
#   ("drive", forward, strafe, seconds)   move while holding the heading
#   ("turn", degrees)                     face this many degrees left of the
#                                         start heading (negative = right)
#   ("hold", seconds)                     stay put, correcting the heading
PLAN = [
    ("turn", 90), ("turn", 180), ("turn", 270), ("turn", 360),
]

# Measured on the reference robot: positive mixer rotation DECREASES IMU
# heading. Convert heading feedback to that motor convention here, without
# changing the owner's verified manual controls, motor inversion, or wiring.
IMU_TO_MIXER_SIGN = -1.0


class MecanumAutonomous:
    """Runs PLAN, steering every step by the IMU."""

    # How long the routine is allowed to run before MotionModule cuts it off.
    # Competition autonomous periods are bounded; so is this. Set it to None
    # for no limit, but then only DISABLE can end a routine that loops.
    duration_seconds = 90.0

    DRIVE_SPEED = 0.35      # power limit while driving a step
    TURN_SPEED = 1.0       # actual motor power, not a multiplier
    APPROACH_SPEED = 0.6   # maximum power near each target
    CORRECTION_SPEED = 0.28 # lower power cap after overshoot, in either direction
    APPROACH_DEGREES = 25
    APPROACH_RATE = 200   # degrees/second at the start of the approach
    FINAL_APPROACH_RATE = 80  # taper to this as the remaining angle shrinks
    CORRECTION_RATE = 12.0  # stay this slow after overshoot, even if undershooting
    TURN_TIMEOUT = 20.0    # allow time for slow recovery; never skip a marker
    LOOP_SECONDS = 0.02     # 50 updates a second
    IMU_READY_TIMEOUT = 5.0  # remain stopped while startup calibration finishes

    def __init__(self, module, drive):
        self.module = module
        self.drive = drive
        # Both programs read the same runtime-managed, built-in Pi IMU.
        self.sensors = getattr(drive, "sensors", None)
        self.heading = getattr(drive, "heading", None) or HeadingController()
        # Dedicated PID state and tuning; no changes to TeleOp heading assist.
        self.turn_heading = TurnPID(kp=0.065, kd=0.0035, derivative_seconds=0.01, max_power=self.TURN_SPEED, integral_power_limit=self.APPROACH_SPEED,
                                    settle_seconds=0.2)
        # move() sets the wheels with no driver assist in the way.
        self.move = getattr(drive, "move", drive.drive)
        self.target = 0.0
        self.progress = {"steps": [list(step) for step in PLAN], "step": None}

    def ready(self):
        return self.sensors is not None and self.sensors.heading() is not None

    def turn_power(self, *, in_place):
        heading = self.sensors.heading()
        if heading is None:
            return None
        rate = getattr(self.sensors, "rate", None)
        return self.heading.power(self.target, heading, rate() if callable(rate) else None, in_place=in_place)

    def drive_for(self, forward, strafe, seconds, stop):
        """Drive or strafe for a while, adding a turn that holds the heading.

        This is gyro-based straight driving: the further off the heading, the
        harder it steers back. The loop also refreshes the motor watchdog.
        """

        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if stop.is_set():
                return False
            turn = self.turn_power(in_place=False)
            if turn is None:        # the IMU dropped out: stop rather than drive blind
                return False
            self.move(forward, strafe, turn / self.DRIVE_SPEED, speed=self.DRIVE_SPEED)
            time.sleep(self.LOOP_SECONDS)
        self.drive.stop()
        return True

    def turn_to(self, target, stop):
        """Correct in either direction until this marker is stable within ±3°."""

        self.target = wrap180(target)
        self.turn_heading.reset()
        settle = Settle(self.turn_heading)
        approaching = False
        approach_rate = self.APPROACH_RATE
        overshot = False
        direction = None
        previous_error = None
        deadline = time.monotonic() + self.TURN_TIMEOUT
        heading = error = None
        try:
            while time.monotonic() < deadline:
                if stop.is_set():
                    return False
                heading = self.sensors.heading()
                if heading is None or not math.isfinite(heading):
                    raise RuntimeError("IMU heading lost; autonomous stopped")
                now = time.monotonic()
                error = wrap180(self.target - heading)
                if direction is None:
                    direction = 1 if error >= 0 else -1
                crossed = (previous_error is not None
                           and previous_error * direction > 0 >= error * direction
                           and abs(error - previous_error) < 180)
                overshot = overshot or crossed
                previous_error = error
                approaching = approaching or abs(error) <= self.APPROACH_DEGREES
                limit = self.APPROACH_SPEED if approaching else self.TURN_SPEED
                rate_limit = None
                if approaching:
                    fraction = max(0.0, min(1.0,
                        (abs(error) - self.turn_heading.tolerance)
                        / (self.APPROACH_DEGREES - self.turn_heading.tolerance)))
                    approach_rate = min(approach_rate, self.FINAL_APPROACH_RATE
                                        + (self.APPROACH_RATE - self.FINAL_APPROACH_RATE) * fraction)
                    rate_limit = approach_rate
                if overshot:
                    limit = min(limit, self.CORRECTION_SPEED)
                    rate_limit = self.CORRECTION_RATE
                turn = self.turn_heading.update(self.target, heading, now, limit=limit, rate_limit=rate_limit)
                still = abs(self.turn_heading.rate) <= self.turn_heading.STOPPED_DPS
                if not still:
                    settle = Settle(self.turn_heading)
                on_target = abs(error) <= self.turn_heading.tolerance
                phase = "settling" if still and on_target else "correction" if overshot else "approach" if approaching else "cruise"
                self.progress = {**self.progress, "target": self.target,
                                 "heading": heading, "error": error,
                                 "tolerance_degrees": self.turn_heading.tolerance,
                                 "turn_phase": phase, "power_limit": limit,
                                 "rate_limit": rate_limit,
                                 "turn_power": turn, "turn_rate": self.turn_heading.rate}
                if still and settle.update(self.target, heading, now):
                    self.progress = {**self.progress, "turn_phase": "reached", "turn_power": 0.0}
                    return True
                self.move(0, 0, turn, speed=1.0)
                time.sleep(self.LOOP_SECONDS)
            marker = self.progress.get("target_degrees", target)
            raise RuntimeError(
                f"Turn to {marker:g}° did not settle within ±{self.turn_heading.tolerance:g}° "
                f"in {self.TURN_TIMEOUT:g}s (IMU target {self.target:.1f}°, "
                f"heading {heading:.1f}°, error {error:+.1f}°)"
            )
        finally:
            self.drive.stop()

    def hold(self, seconds, stop):
        """Stay still, nudging the heading back if the robot was bumped."""

        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if stop.is_set():
                return False
            turn = self.turn_power(in_place=True)
            if turn is None:
                return False
            self.move(0, 0, turn, speed=1.0)
            time.sleep(self.LOOP_SECONDS)
        self.drive.stop()
        return True

    def run(self, stop):
        """Called once when the operator starts autonomous."""

        self.progress = {"steps": [list(step) for step in PLAN], "step": None}
        try:
            deadline = time.monotonic() + self.IMU_READY_TIMEOUT
            while not self.ready():
                if stop.is_set():
                    return
                if time.monotonic() >= deadline:
                    detail = getattr(self.sensors, "describe", lambda: "No usable heading")()
                    raise RuntimeError(f"Built-in IMU is not ready; autonomous stayed stopped. {detail}")
                self.progress = {**self.progress, "waiting_for_imu": True}
                stop.wait(self.LOOP_SECONDS)
            self.progress = {**self.progress, "waiting_for_imu": False}
            start = self.sensors.heading()
            self.target = start
            for index, step in enumerate(PLAN):
                if stop.is_set():
                    return
                self.progress = {**self.progress, "step": index, "start_heading": start}
                kind = step[0]
                if kind == "drive":
                    _, forward, strafe, seconds = step
                    done = self.drive_for(forward, strafe, seconds, stop)
                elif kind == "turn":
                    self.progress = {**self.progress, "target_degrees": step[1]}
                    done = self.turn_to(start + step[1], stop)
                elif kind == "hold":
                    done = self.hold(step[1], stop)
                else:
                    raise ValueError(f"Unknown autonomous step: {step!r}")
                if not done:
                    if not stop.is_set():
                        raise RuntimeError("IMU heading lost; autonomous stopped")
                    return
                self.progress = {**self.progress, "completed": index + 1}
        finally:
            self.drive.stop()


def create_autonomous(module, drive):
    """Required entry point. Return anything with run(stop)."""

    # This separate program receives an idle drive from robot.py. Build its
    # own confirmed four-wheel mixer; the core already owns the Pi gyro.
    if not callable(getattr(drive, "move", None)) or getattr(drive, "sensors", None) is None:
        from types import SimpleNamespace
        from motion_module.mecanum import MecanumTestDrive

        mixer = MecanumTestDrive(module)
        imu = module.imu

        def heading_move(forward, strafe, rotate, speed=1.0):
            return mixer.drive(forward, strafe, IMU_TO_MIXER_SIGN * rotate, speed=speed)

        drive = SimpleNamespace(
            drive=heading_move, move=heading_move, stop=mixer.stop,
            sensors=imu, heading=HeadingController(),
        )
    return MecanumAutonomous(module, drive)
