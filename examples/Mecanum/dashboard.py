"""Optional Driver Station telemetry for the Mecanum example.

MotionModule finds this file automatically because it sits beside robot.py.
Delete it and driving still works. Sensors are set up in sensors.py and
reach this file through drive.sensors, so the Driver Station shows exactly
what the robot code reads.
"""

from motion_module.telemetry import CameraFeed, IMUReading, TelemetryDashboard


# Browser-readable MJPEG URLs from the robot or camera server. Empty URLs keep
# the two sample viewports visible as clearly labelled offline placeholders.
# Common examples look like "http://motionmodule.local:1181/?action=stream".
FRONT_CAMERA_URL = ""
REAR_CAMERA_URL = ""


class MecanumDashboard(TelemetryDashboard):
    """Cameras, the IMU, and the GIGA's readings for the Driver Station."""

    def __init__(self, module, drive):
        self.module = module
        self.drive = drive
        self.sensors = getattr(drive, "sensors", None)

    def driver_bindings(self):
        """Which keys the Driver Station listens for on this robot.

        This is the competition console's layout and belongs to the robot, so
        it lives here rather than in a browser. It has nothing to do with the
        Drive debug page, which each browser remaps for itself.

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

    def cameras(self):
        # The Driver Station lets the operator show either camera or both.
        # Each viewport remains square; at most two feeds are accepted.
        return [
            CameraFeed(
                "Front camera",
                FRONT_CAMERA_URL,
                connected=bool(FRONT_CAMERA_URL),
                detail="Forward C920 / C270 view",
            ),
            CameraFeed(
                "Rear camera",
                REAR_CAMERA_URL,
                connected=bool(REAR_CAMERA_URL),
                detail="Rear C920 / C270 view",
            ),
        ]

    def imu(self):
        # The heading dial shows the first IMU in sensors.py; the GIGA card
        # below it lists every IMU and pin.
        if self.sensors is None or not self.sensors.imus:
            return IMUReading(name="Robot IMU", connected=False, calibrated=False,
                              detail="Declare an IMU in sensors.py.")
        return self.sensors.imus[0].reading()

    def usb_controllers(self):
        # Every pin and IMU on the GIGA, as the robot code sees them.
        return [self.sensors.giga.snapshot()] if self.sensors is not None else []


def create_dashboard(module, drive):
    """Optional entry point discovered automatically by MotionModule."""

    return MecanumDashboard(module, drive)
