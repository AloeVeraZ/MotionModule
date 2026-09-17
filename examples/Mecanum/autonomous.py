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
    """Drive forward, turn a quarter left, strafe right: written to be replaced."""

    # How long the routine is allowed to run before MotionModule cuts it off.
    # Competition autonomous periods are bounded; so is this. Set it to None
    # for no limit, but then only DISABLE can end a routine that loops.
    duration_seconds = 15.0

    # Turning by the IMU: full turn power while more than TURN_SLOW_DEGREES
    # away, slowing down after that, and done within TURN_TOLERANCE_DEGREES.
    TURN_SLOW_DEGREES = 30.0
    TURN_MINIMUM_POWER = 0.35
    TURN_TOLERANCE_DEGREES = 2.0

    def __init__(self, module, drive):
        self.module = module
        self.drive = drive
        # sensors.py, created by robot.py. None if the robot has no sensors.
        self.sensors = getattr(drive, "sensors", None)

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

    def turn_to(self, target, stop, speed=0.4, timeout=3.0):
        """Turn in place until the IMU heading reads `target` degrees.

        Headings count up turning left, the same way a positive rotate turns,
        so the power is simply the remaining angle, capped at full.
        """

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if stop.is_set():
                return False
            heading = self.sensors.heading()
            if heading is None:  # the IMU dropped out: stop turning blind
                break
            error = (target - heading + 180.0) % 360.0 - 180.0
            if abs(error) <= self.TURN_TOLERANCE_DEGREES:
                break
            power = max(-1.0, min(1.0, error / self.TURN_SLOW_DEGREES))
            if abs(power) < self.TURN_MINIMUM_POWER:
                power = self.TURN_MINIMUM_POWER if power > 0 else -self.TURN_MINIMUM_POWER
            self.drive.drive(0, 0, power, speed=speed)
            time.sleep(0.02)
        self.drive.stop()
        return not stop.is_set()

    def run(self, stop):
        """Called once when the operator starts autonomous."""

        imu_ready = self.sensors is not None and self.sensors.heading() is not None
        if imu_ready:
            self.sensors.zero_heading()             # the robot's start is 0°

        if not self.move(1, 0, 0, 1.5, stop):       # forward
            return
        if imu_ready:
            turned = self.turn_to(90, stop)         # a quarter turn left, by the IMU
        else:
            turned = self.move(0, 0, 1, 0.8, stop)  # no IMU: turn left for a set time
        if not turned:
            return
        if not self.move(0, 1, 0, 1.0, stop):       # strafe right
            return
        self.drive.stop()
        self.wait(0.2, stop)


def create_autonomous(module, drive):
    """Required entry point. Return anything with run(stop)."""

    return MecanumAutonomous(module, drive)
