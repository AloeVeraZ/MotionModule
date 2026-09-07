"""Optional autonomous routine for the Mecanum sample.

This file is optional. Delete it and the robot still drives; the Driver
Station simply shows no autonomous mode. Add it and an AUTONOMOUS button
appears next to TELEOPERATED, and RUN AUTO starts what is written here.

MotionModule calls `create_autonomous(module, drive)` once at startup, then
calls `run(stop)` on the object it returns each time the operator starts
autonomous.

The one rule: check `stop.is_set()` inside every wait and return as soon as it
is true. The operator pressing DISABLE sets that flag, and MotionModule stops
every output immediately whether or not this code notices, but a routine that
returns promptly is a routine you can trust.
"""

import time


class MecanumAutonomous:
    """A short drive-forward-and-turn routine, written to be replaced."""

    # How long the routine is allowed to run before MotionModule cuts it off.
    # Competition autonomous periods are bounded; so is this. Set it to None
    # for no limit, but then only DISABLE can end a routine that loops.
    duration_seconds = 15.0

    def __init__(self, module, drive):
        self.module = module
        self.drive = drive

    def wait(self, seconds, stop):
        """Sleep in slices so DISABLE is noticed quickly. False means stop."""

        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if stop.is_set():
                return False
            time.sleep(0.02)
        return True

    def move(self, forward, strafe, rotate, seconds, stop, speed=0.3):
        """Hold one drive command for a while, refreshing the watchdog.

        The motor watchdog stops the robot if commands stop arriving, so an
        autonomous step is a loop that keeps sending, not one call and a sleep.
        """

        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if stop.is_set():
                return False
            self.drive.drive(forward, strafe, rotate, speed=speed)
            time.sleep(0.05)
        return True

    def run(self, stop):
        """Called once when the operator starts autonomous."""

        if not self.move(1, 0, 0, 1.5, stop):      # forward
            return
        if not self.move(0, 0, 1, 0.8, stop):      # turn counter-clockwise
            return
        if not self.move(0, 1, 0, 1.0, stop):      # strafe right
            return
        self.drive.stop()
        self.wait(0.2, stop)


def create_autonomous(module, drive):
    """Required entry point. Return anything with run(stop)."""

    return MecanumAutonomous(module, drive)
