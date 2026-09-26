"""Optional Driver Station telemetry for the Mecanum example.

MotionModule finds this file automatically because it sits beside robot.py.
Delete it and driving still works. Sensors are set up in sensors.py and
reach this file through drive.sensors, so the Driver Station shows exactly
what the robot code reads.
"""

from motion_module.telemetry import CameraFeed, IMUReading, TelemetryDashboard


# An external streamer's browser-readable MJPEG URL, e.g.
# "http://motionmodule.local:1181/?action=stream". Leave this blank - it's
# blank by default - and MotionModule streams a USB camera plugged into the
# Pi for "Front" itself, with no server of your own to run.
FRONT_CAMERA_URL = ""


class MecanumDashboard(TelemetryDashboard):
    """The Driver Station's controls, cameras and Pi IMU."""

    def __init__(self, module, drive):
        self.module = module
        self.drive = drive
        self.sensors = getattr(drive, "sensors", None)

    def driver_bindings(self):
        """Which keys the Driver Station listens for on this robot.

        This is the competition console's layout and belongs to the robot, so
        it lives here rather than in a browser. It has nothing to do with the
        fixed bindings in Debug's Mecanum Test.

        Return only what you want to move. Anything left out keeps its default:
        W/S drive, A/D strafe, Q/E turn, space disables and stops.
        """

        return {
            "forward": "w",
            "back": "s",
            "left": "a",
            "right": "d",
            "turn_left": "q",
            "turn_right": "e",
            "stop": " ",
        }

    def gamepad_sticks(self):
        """Which game-controller stick drives, strafes and turns.

        Give each motion one of "left_x", "left_y", "right_x" or "right_y".
        Pushing that stick up or right drives forward, strafes right or turns
        right. Put "-" in front to flip it ("-left_y"), or use None to switch
        a motion off; a tank drive, for one, has no strafe. "deadzone" (0 to
        0.5) ignores the wobble of a stick at rest, and a "curve" above 1 (up
        to 3) gives finer control near the middle.
        """

        return {
            "forward": "left_y",
            "strafe": "left_x",
            "rotate": "right_x",
            "deadzone": 0.12,
            "curve": 1.0,
        }

    def gamepad_buttons(self):
        """Which game-controller buttons trigger an action on this robot.

        Written the same way as driver_bindings: return only what you want to
        change; a face button ("a", "b", "x", "y"), a bumper, a trigger or a
        D-pad direction can take any of driver_bindings' six actions, or
        "stop"/"estop" to disable the robot instantly. This sample keeps the
        defaults explicit: the D-pad's down button stops the robot and the
        right trigger is the emergency stop.
        """

        return {
            "dpad_down": "stop",
            "right_trigger": "estop",
        }

    def touch_sticks(self):
        """The two on-screen sticks a phone or tablet drives with.

        Written the same way as gamepad_sticks(). A stick given two motions
        moves all the way round; a stick given one moves only that way, so
        the right stick here only goes left and right. "rotate": "buttons"
        swaps the turning stick for Turn left and Turn right buttons.
        """

        return {
            "forward": "left_y",
            "strafe": "left_x",
            "rotate": "right_x",
            "deadzone": 0.1,
            "curve": 1.0,
        }

    def touch_panels(self):
        """Extra panels for a phone or tablet.

        A touchscreen shows robot control, the sticks and the cameras. Add
        any of "status", "mechanisms", "imu", "pi_inputs" and
        "usb_controllers" to show those too; a computer always shows all.
        """

        return []

    def cameras(self):
        # Only one camera is wired up by default. A second USB camera on the
        # Pi still shows up on its own, bringing up the Driver Station's
        # Front/Both/Rear toggle without any code here - but naming it
        # "Rear", or giving it its own external streamer's URL, takes a
        # second CameraFeed the same way this one is written:
        #
        #     REAR_CAMERA_URL = ""
        #     return [
        #         CameraFeed("Front camera", FRONT_CAMERA_URL,
        #                    connected=bool(FRONT_CAMERA_URL), detail="Forward C920 / C270 view"),
        #         CameraFeed("Rear camera", REAR_CAMERA_URL,
        #                    connected=bool(REAR_CAMERA_URL), detail="Rear C920 / C270 view"),
        #     ]
        return [
            CameraFeed(
                "Front camera",
                FRONT_CAMERA_URL,
                connected=bool(FRONT_CAMERA_URL),
                detail="Forward C920 / C270 view",
            ),
        ]

    def imu(self):
        if self.sensors is None:
            return IMUReading(name="Robot IMU", connected=False, calibrated=False,
                              detail="Pi MPU6500 is not configured in sensors.py.")
        return self.sensors.reading()

    def usb_controllers(self):
        # No additional USB sensors are declared by this robot.
        return []


def create_dashboard(module, drive):
    """Optional entry point discovered automatically by MotionModule."""

    return MecanumDashboard(module, drive)
