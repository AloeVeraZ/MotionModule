"""Optional autonomous routine for the Mecanum sample: four IMU-guided turns.

This file is optional. Delete it and the robot still drives; the Driver
Station explains that no routine is loaded. Choose Autonomous, Enable,
then Start Autonomous to run what is written here.

MotionModule calls `create_autonomous(module, drive)` once at startup, then
calls `run(stop)` on the object it returns each time the operator starts
autonomous.

What it does: turn left to 90, 180, 270 and 360 degrees from the starting
direction, settling within two degrees at each stop. It never translates.
Change PLAN to make your own. The heading loop is the one FTC teams use (see
motion_module/heading.py) and shares its tuning, HEADING in robot.py, with
the Driver Station's snap turns.

It never zeroes the IMU. Every angle in PLAN counts from the way the robot
faces when Start Autonomous is pressed, so line the robot up first; press Zero IMU in
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
    ("turn", 90), ("turn", 180), ("turn", 270), ("turn", 360),
]


class MecanumAutonomous:
    """Runs PLAN, steering every step by the IMU."""

    # How long the routine is allowed to run before MotionModule cuts it off.
    # Competition autonomous periods are bounded; so is this. Set it to None
    # for no limit, but then only DISABLE can end a routine that loops.
    duration_seconds = 30.0

    DRIVE_SPEED = 0.35      # power limit while driving a step
    TURN_TIMEOUT = 6.0      # seconds before failing a turn, never skipping it
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
                raise RuntimeError("IMU heading lost; autonomous stopped")
            self.progress = {**self.progress, "target": self.target,
                             "heading": heading, "error": wrap180(self.target - heading)}
            if settle.update(self.target, heading, time.monotonic()):
                break
            turn = self.turn_power(in_place=True)
            if turn is None:
                raise RuntimeError("IMU heading lost; autonomous stopped")
            self.move(0, 0, turn, speed=1.0)
            time.sleep(self.LOOP_SECONDS)
        else:
            raise RuntimeError(f"Turn to {self.target:g}° did not settle within {self.TURN_TIMEOUT:g}s")
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

        self.progress = {"steps": [list(step) for step in PLAN], "step": None}
        try:
            if not self.ready():
                raise RuntimeError("IMU is not ready; calibrate it before running autonomous")
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

    # Upgrade support: older owner-edited Mecanum projects may have neither
    # sensors nor a raw move() method. Keep their teleop code and use the
    # confirmed channel mixer for this bundled routine only.
    if not callable(getattr(drive, "move", None)) or getattr(drive, "sensors", None) is None:
        from types import SimpleNamespace
        from motion_module.imu import IMUConfig
        from motion_module.mecanum import MecanumTestDrive

        mixer = MecanumTestDrive(module)
        imu = module.local_imu(IMUConfig("Main IMU", address=0x68))
        drive = SimpleNamespace(
            drive=mixer.drive, move=mixer.drive, stop=mixer.stop,
            sensors=imu, heading=HeadingController(),
        )
    return MecanumAutonomous(module, drive)
