"""The IMU heading loop: drift correction, 90° snap turns and the autonomous square.

A small simulated robot stands in for the real one: its turn rate follows the
turn the wheels ask for (with a lag, like a real drivetrain) plus a steady
drift, the way a mecanum robot curves when its wheels are not matched. These
tests show the loop's logic and direction are right. They do not tune it:
gains for the real robot still have to be checked on the floor.
"""

import sys
import threading
import unittest
from pathlib import Path

from motion_module.heading import HeadingController, HeadingHold, Settle, nearest_step, wrap180
from motion_module.telemetry import normalize_snapshot

PROJECT_DIR = Path(__file__).resolve().parents[1] / "examples" / "Mecanum"
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import autonomous as sample_autonomous  # noqa: E402
from robot import HEADING, MecanumDrive  # noqa: E402


class SimRobot:
    """Heading physics for a mecanum robot, driven by its four wheel powers."""

    DEGREES_PER_SECOND = 300.0   # turn rate at full turn power
    LAG_SECONDS = 0.08           # how quickly the rate follows the wheels
    FRICTION = 0.12              # turn power lost to the carpet before it turns

    def __init__(self, heading=0.0, drift=0.0):
        self.now = 0.0
        self.value = heading          # unwrapped degrees, left positive
        self.rate_value = 0.0
        self.drift = drift            # degrees/second the robot curves by itself
        self.outputs = {}
        self.zeroed = False
        self.imu_ok = True

    # the module the drive writes to
    def set_motors(self, outputs):
        self.outputs = dict(outputs)

    def stop_all(self):
        self.outputs = {name: 0 for name in self.outputs}

    # the sensors the drive reads
    def heading(self):
        return wrap180(self.value) if self.imu_ok else None

    def rate(self):
        return self.rate_value if self.imu_ok else None

    def zero_heading(self):
        self.zeroed = True
        return True

    def turn(self):
        o = self.outputs
        if not o:
            return 0.0
        return (o["front_left"] - o["rear_left"] + o["front_right"] - o["rear_right"]) / 4

    def moving(self):
        return any(abs(value) > 1e-9 for value in self.outputs.values())

    def advance(self, seconds):
        push = self.turn()
        # Friction only holds a robot that is not already rolling: turning
        # from a standstill needs a breakaway push, steering while driving not.
        o = self.outputs or {"front_left": 0, "rear_left": 0, "front_right": 0, "rear_right": 0}
        forward = (o["front_left"] + o["rear_left"] + o["front_right"] + o["rear_right"]) / 4
        strafe = (o["front_left"] - o["rear_left"] - o["front_right"] + o["rear_right"]) / 4
        friction = 0.0 if abs(forward) + abs(strafe) > 0.05 else self.FRICTION
        usable = max(0.0, abs(push) - friction) / (1 - friction)
        wanted = (usable if push > 0 else -usable) * self.DEGREES_PER_SECOND
        wanted += self.drift if self.moving() else 0.0
        steps = max(1, int(seconds / 0.005))
        for _ in range(steps):
            dt = seconds / steps
            self.rate_value += (wanted - self.rate_value) * min(1.0, dt / self.LAG_SECONDS)
            self.value += self.rate_value * dt
        self.now += seconds


def assisted_drive(robot):
    drive = MecanumDrive(robot, sensors=robot)
    drive.assist = HeadingHold(HEADING, clock=lambda: robot.now)
    return drive


def teleop(robot, drive, seconds, forward=0.0, strafe=0.0, rotate=0.0, speed=0.5):
    """The Driver Station's 80 ms drive commands."""

    for _ in range(int(round(seconds / 0.08))):
        drive.drive(forward, strafe, rotate, speed)
        robot.advance(0.08)


class HeadingMathTests(unittest.TestCase):
    def test_errors_wrap_the_short_way_round(self):
        controller = HeadingController()
        self.assertEqual(controller.error(-170, 170), 20)
        self.assertEqual(controller.error(170, -170), -20)
        self.assertEqual(wrap180(270), -90)
        self.assertEqual(wrap180(-180), -180)

    def test_nearest_step_rounds_to_the_90_degree_grid(self):
        for heading, step in ((3, 0), (44, 0), (46, 90), (-83, -90), (179, -180), (-136, -180)):
            self.assertEqual(abs(wrap180(nearest_step(heading) - step)), 0, heading)

    def test_power_turns_toward_the_target_and_left_is_positive(self):
        controller = HeadingController()
        self.assertGreater(controller.power(90, 0), 0)
        self.assertLess(controller.power(-90, 0), 0)
        self.assertEqual(controller.power(90, 0), controller.max_power)

    def test_minimum_power_only_pushes_and_only_in_place(self):
        controller = HeadingController(kp=0.02, min_turn_power=0.2, tolerance=2)
        self.assertEqual(controller.power(5, 0), 0.2)                       # boosted in place
        self.assertAlmostEqual(controller.power(5, 0, in_place=False), 0.1)  # gentle while driving
        self.assertEqual(controller.power(1, 0), 0.0)                       # already there
        # Turning fast toward the target, the damping brakes; never boost a brake.
        braking = controller.power(5, 0, rate=200)
        self.assertLess(braking, 0)
        self.assertGreater(braking, -0.2)

    def test_settle_needs_the_heading_to_stay_in_tolerance(self):
        settle = Settle(HeadingController(tolerance=2, settle_seconds=0.1))
        self.assertFalse(settle.update(90, 89, 0.0))
        self.assertFalse(settle.update(90, 89, 0.05))
        self.assertFalse(settle.update(90, 95, 0.08))   # swung out: starts again
        self.assertFalse(settle.update(90, 90, 0.1))
        self.assertTrue(settle.update(90, 90.5, 0.21))


class HeadingHoldTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.hold = HeadingHold(clock=lambda: self.now)

    def test_the_driver_turning_is_always_in_charge(self):
        self.assertIsNone(self.hold.update(10, 0, 1, 0, 0.5))
        self.assertIsNone(self.hold.target)

    def test_locks_after_the_driver_lets_go_then_corrects_while_driving(self):
        self.hold.update(10, 0, 0, 0, 0.5)        # turning
        self.now = 0.1
        self.assertIsNone(self.hold.update(12, 0, 1, 0, 0))   # still coasting out
        self.now = 0.5
        self.assertAlmostEqual(self.hold.update(12, 0, 1, 0, 0), 0.0)
        self.assertEqual(self.hold.target, 12)
        self.assertGreater(self.hold.update(7, 0, 1, 0, 0), 0)   # drifted right: turn left
        self.assertLess(self.hold.update(17, 0, 0, 1, 0), 0)     # strafing counts too

    def test_standing_still_it_never_twitches(self):
        self.now = 1.0
        self.hold.update(0, 0, 1, 0, 0)
        self.assertIsNone(self.hold.update(20, 0, 0, 0, 0))

    def test_no_imu_means_no_assist(self):
        self.now = 1.0
        self.hold.update(0, 0, 1, 0, 0)
        self.assertIsNone(self.hold.update(None, None, 1, 0, 0))
        self.assertIsNone(self.hold.target)

    def test_a_runaway_switches_holding_off_and_says_why(self):
        self.now = 1.0
        self.hold.update(0, 0, 1, 0, 0)
        self.assertIsNone(self.hold.update(60, 0, 1, 0, 0))
        self.assertFalse(self.hold.enabled)
        self.assertIn("left turn", self.hold.message)
        self.hold.set_enabled(True)
        self.assertEqual(self.hold.message, "")

    def test_snap_targets_the_next_90_and_presses_stack(self):
        self.assertEqual(self.hold.snap(3, +1), 90)
        self.assertEqual(self.hold.snap(10, +1), -180)    # pressed again mid-turn: 180°
        self.hold.cancel()
        self.assertEqual(self.hold.snap(-80, -1), -180)   # -90 is nearest, then right: -180
        self.hold.cancel()
        self.assertEqual(self.hold.snap(100, -1), 0)
        self.assertIsNone(HeadingHold().snap(None, 1))

    def test_moving_the_turn_stick_cancels_a_snap(self):
        self.hold.snap(0, 1)
        self.assertIsNone(self.hold.update(20, 0, 0, 0, -0.6))
        self.assertFalse(self.hold.snapping)

    def test_a_snap_turning_the_wrong_way_stops(self):
        self.hold.snap(0, 1)
        self.assertEqual(self.hold.update(-60, 0, 0, 0, 0), 0.0)
        self.assertFalse(self.hold.snapping)
        self.assertIn("wrong way", self.hold.message)

    def test_snap_works_even_with_heading_hold_off(self):
        self.hold.set_enabled(False)
        self.hold.snap(0, 1)
        self.assertGreater(self.hold.update(0, 0, 0, 0, 0), 0)


class SimulatedTeleOpTests(unittest.TestCase):
    def test_driving_forward_with_drift_stays_straight(self):
        free = SimRobot(drift=15)
        teleop(free, MecanumDrive(free), 3, forward=1)       # no sensors: no assist
        self.assertGreater(free.value, 40)                   # it curves on its own

        robot = SimRobot(drift=15)
        teleop(robot, assisted_drive(robot), 3, forward=1)
        self.assertLess(abs(robot.value), 5)

    def test_strafing_with_drift_stays_straight(self):
        robot = SimRobot(drift=-12)
        teleop(robot, assisted_drive(robot), 3, strafe=1)
        self.assertLess(abs(robot.value), 5)

    def test_after_a_manual_turn_it_holds_the_new_heading(self):
        robot = SimRobot(drift=10)
        drive = assisted_drive(robot)
        teleop(robot, drive, 0.8, rotate=0.5)
        teleop(robot, drive, 0.5)                             # let go, coast, lock
        locked = robot.value
        self.assertGreater(locked, 30)
        teleop(robot, drive, 3, forward=1)
        self.assertLess(abs(robot.value - locked), 5)

    def test_snap_turns_land_on_each_90_without_a_big_overshoot(self):
        robot = SimRobot(heading=4)
        drive = assisted_drive(robot)
        for expected in (90, 180, -90, 0):
            drive.control("turn_left_90", 1)
            peak = 0.0
            for _ in range(40):                                # 3.2 s of 80 ms commands
                drive.drive(0, 0, 0, 0.5)
                robot.advance(0.08)
                peak = max(peak, wrap180(robot.value - expected))
            self.assertLess(abs(wrap180(robot.value - expected)), 3, expected)
            self.assertLess(peak, 10, expected)
            self.assertFalse(drive.assist.snapping)
        drive.control("turn_right_90", 1)
        teleop(robot, drive, 3.2)
        self.assertLess(abs(wrap180(robot.value + 90)), 3)

    def test_speed_limit_scales_the_command_not_the_correction(self):
        robot = SimRobot()
        drive = assisted_drive(robot)
        teleop(robot, drive, 0.5, forward=0.2, speed=0.25)     # lock at 0
        robot.value = -3
        robot.rate_value = 0.0
        drive.drive(0.2, 0, 0, 0.25)
        slow = robot.turn()
        drive.drive(0.2, 0, 0, 1.0)
        self.assertGreater(slow, 0)
        self.assertAlmostEqual(slow, robot.turn(), delta=0.005)

    def test_move_is_never_assisted(self):
        robot = SimRobot()
        drive = assisted_drive(robot)
        teleop(robot, drive, 0.5, forward=1)
        robot.value = -20
        drive.move(1, 0, 0, speed=0.5)
        self.assertEqual(robot.turn(), 0)

    def test_heading_hold_can_be_switched_off_and_on(self):
        robot = SimRobot(drift=15)
        drive = assisted_drive(robot)
        self.assertEqual(drive.control("heading_hold", 1), {"heading_hold": False})
        teleop(robot, drive, 3, forward=1)
        self.assertGreater(robot.value, 40)
        self.assertEqual(drive.control("heading_hold", 1), {"heading_hold": True})

    def test_zero_imu_is_only_the_button_and_forgets_the_old_target(self):
        robot = SimRobot()
        drive = assisted_drive(robot)
        teleop(robot, drive, 1, forward=1)
        self.assertFalse(robot.zeroed)
        drive.control("zero_heading", 1)
        self.assertTrue(robot.zeroed)
        self.assertIsNone(drive.assist.target)


class FakeTime:
    """time.monotonic and time.sleep for autonomous.py, moving the simulation."""

    def __init__(self, robot):
        self.robot = robot

    def monotonic(self):
        return self.robot.now

    def sleep(self, seconds):
        self.robot.advance(seconds)


class AutonomousSquareTests(unittest.TestCase):
    def run_plan(self, robot, stop=None):
        drive = MecanumDrive(robot, sensors=robot)
        routine = sample_autonomous.MecanumAutonomous(robot, drive)
        original = sample_autonomous.time
        sample_autonomous.time = FakeTime(robot)
        try:
            routine.run(stop or threading.Event())
        finally:
            sample_autonomous.time = original
        return routine

    def test_the_square_ends_facing_where_it_started_without_zeroing(self):
        robot = SimRobot(heading=30, drift=8)
        headings = []
        original = robot.advance

        def recording(seconds):
            original(seconds)
            headings.append(robot.value)

        robot.advance = recording
        self.run_plan(robot)
        self.assertFalse(robot.zeroed)
        self.assertLess(abs(wrap180(robot.value - 30)), 3)
        # It really turned all the way round, in 90° steps, to the left.
        self.assertGreater(max(headings), 30 + 350)
        self.assertEqual(set(robot.outputs.values()), {0})
        self.assertLess(robot.now, sample_autonomous.MecanumAutonomous.duration_seconds)

    def test_without_an_imu_it_does_not_move(self):
        robot = SimRobot()
        robot.imu_ok = False
        self.run_plan(robot)
        self.assertFalse(robot.moving())
        self.assertEqual(robot.now, 0.0)

    def test_losing_the_imu_mid_run_stops_the_robot(self):
        robot = SimRobot()
        original = robot.advance

        def failing(seconds):
            original(seconds)
            if robot.now > 0.5:
                robot.imu_ok = False

        robot.advance = failing
        self.run_plan(robot)
        self.assertFalse(robot.moving())
        self.assertLess(robot.now, 1.0)

    def test_disable_stops_it(self):
        stop = threading.Event()
        stop.set()
        robot = SimRobot()
        self.run_plan(robot, stop)
        self.assertFalse(robot.moving())


class ControlBindingTests(unittest.TestCase):
    def test_keys_and_buttons_can_press_a_declared_control(self):
        snapshot = normalize_snapshot({
            "driver_bindings": {"turn_left_90": "Z", "turn_right_90": "c", "bad name": "x",
                                "steal_w": "w", "forward": "w"},
            "gamepad_buttons": {"left_bumper": "turn_left_90", "a": "Not-A-Name", "b": "forward"},
        })
        self.assertEqual(snapshot["control_keys"], {"turn_left_90": "z", "turn_right_90": "c"})
        self.assertEqual(snapshot["control_buttons"], {"left_bumper": "turn_left_90"})
        self.assertEqual(snapshot["gamepad_buttons"]["b"], "forward")
        self.assertEqual(snapshot["driver_bindings"]["forward"], "w")


if __name__ == "__main__":
    unittest.main()
