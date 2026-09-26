"""Optional autonomous routine for the Mecanum sample: an IMU-guided square.

This file is optional. Delete it and the robot still drives; the Driver
Station simply shows no autonomous mode. Add it and an AUTONOMOUS button
appears next to TELEOPERATED, and RUN AUTO starts what is written here.

MotionModule calls `create_autonomous(module, drive)` once at startup, then
calls `run(stop)` on the object it returns each time the operator starts
autonomous.

What it does: drive forward holding its heading, turn exactly 90° left by the
IMU, and repeat four times, finishing where it started, facing the same way.
Change PLAN to make your own. The heading loop is the one FTC teams use (see
motion_module/heading.py) and shares its tuning, HEADING in robot.py, with
the Driver Station's snap turns.

It never zeroes the IMU. Every angle in PLAN counts from the way the robot
faces when RUN AUTO is pressed, so line the robot up first; press Zero IMU in
the Driver Station only when you want to set 0° yourself.

The robot has no wheel encoders, so a "drive" step goes for a set time, not
a set distance. Without a working IMU the routine does not move at all.

The one rule: check `stop.is_set()` inside every wait and return as soon as it
is true. The operator pressing DISABLE sets that flag, and MotionModule stops
every output immediately whether or not this code notices, but a routine that
returns promptly is a routine you can trust.
"""

import time

from motion_module.heading import HeadingController, Settle, wrap180


# Each step is one of:
#   ("drive", forward, strafe, seconds)   move while holding the heading
#   ("turn", degrees)                     face this many degrees left of the
#                                         start heading (negative = right)
#   ("hold", seconds)                     stay put, correcting the heading
PLAN = [
    ("drive", 1.0, 0.0, 1.0), ("turn", 90), ("hold", 0.3),
    ("drive", 1.0, 0.0, 1.0), ("turn", 180), ("hold", 0.3),
    ("drive", 1.0, 0.0, 1.0), ("turn", 270), ("hold", 0.3),
    ("drive", 1.0, 0.0, 1.0), ("turn", 360), ("hold", 0.3),
]


class MecanumAutonomous:
    """Runs PLAN, steering every step by the IMU."""

    # How long the routine is allowed to run before MotionModule cuts it off.
    # Competition autonomous periods are bounded; so is this. Set it to None
    # for no limit, but then only DISABLE can end a routine that loops.
    duration_seconds = 30.0

    DRIVE_SPEED = 0.35      # power limit while driving a step
    TURN_TIMEOUT = 3.0      # seconds a turn may take before moving on
    LOOP_SECONDS = 0.02     # 50 updates a second

    def __init__(self, module, drive):
        self.module = module
        self.drive = drive
        # sensors.py, created by robot.py. None if the robot has no sensors.
        self.sensors = getattr(drive, "sensors", None)
        # The same tuning as the Driver Station's snap turns (robot.py).
        self.heading = getattr(drive, "heading", None) or HeadingController()
        # move() sets the wheels with no driver assist in the way.
        self.move = getattr(drive, "move", drive.drive)
        self.target = 0.0

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

        This is FIRST's gyro drive-straight: the further off the heading, the
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
        """Turn on the spot to `target`, finished once it stays there briefly."""

        self.target = wrap180(target)
        settle = Settle(self.heading)
        deadline = time.monotonic() + self.TURN_TIMEOUT
        while time.monotonic() < deadline:
            if stop.is_set():
                return False
            heading = self.sensors.heading()
            if heading is None:
                return False
            if settle.update(self.target, heading, time.monotonic()):
                break
            turn = self.turn_power(in_place=True)
            self.move(0, 0, turn, speed=1.0)
            time.sleep(self.LOOP_SECONDS)
        self.drive.stop()
        return True

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

        if not self.ready():
            print("Autonomous: the IMU is not ready, so the robot will not move.")
            return
        start = self.sensors.heading()
        self.target = start
        for step in PLAN:
            kind = step[0]
            if kind == "drive":
                _, forward, strafe, seconds = step
                done = self.drive_for(forward, strafe, seconds, stop)
            elif kind == "turn":
                done = self.turn_to(start + step[1], stop)
            elif kind == "hold":
                done = self.hold(step[1], stop)
            else:
                raise ValueError(f"Unknown autonomous step: {step!r}")
            if not done:
                break
        self.drive.stop()


def create_autonomous(module, drive):
    """Required entry point. Return anything with run(stop)."""

    return MecanumAutonomous(module, drive)
