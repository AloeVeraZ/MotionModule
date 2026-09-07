"""Optional Driver Station telemetry for the Mecanum example.

MotionModule finds this file automatically because it sits beside robot.py.
Delete it and driving still works; edit it when the robot gains cameras, an
IMU, analog inputs, or digital inputs.
"""

from motion_module.telemetry import (
    CameraFeed,
    IMUReading,
    SensorReading,
    TelemetryDashboard,
)


# Browser-readable MJPEG URLs from the robot or camera server. Empty URLs keep
# the two sample viewports visible as clearly labelled offline placeholders.
# Common examples look like "http://motionmodule.local:1181/?action=stream".
FRONT_CAMERA_URL = ""
REAR_CAMERA_URL = ""


class MecanumDashboard(TelemetryDashboard):
    """Replace the placeholder reads below with this robot's sensor objects."""

    def __init__(self, module, drive):
        self.module = module
        self.drive = drive

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
        # When an IMU is added, return its live yaw, pitch, roll, and yaw rate.
        # Keep the robot still while the device calibrates, then set calibrated.
        return IMUReading(
            name="Robot IMU",
            connected=False,
            calibrated=False,
            detail="Connect a gyro/IMU and replace this placeholder read.",
        )

    def sensors(self):
        # Up to 20 analog, digital, or text readings can be returned here.
        # These placeholders document typical inputs without pretending that
        # unconnected hardware is live.
        return [
            SensorReading(
                "Front range",
                None,
                kind="analog",
                unit="mm",
                channel="ADC 0",
                connected=False,
                minimum=0,
                maximum=2000,
                detail="Example distance or analog range sensor",
            ),
            SensorReading(
                "Intake beam",
                None,
                kind="digital",
                channel="DIO 0",
                connected=False,
                detail="Example beam-break input",
            ),
            SensorReading(
                "Forward limit",
                None,
                kind="digital",
                channel="DIO 1",
                connected=False,
                detail="Example limit-switch input",
            ),
        ]


def create_dashboard(module, drive):
    """Optional entry point discovered automatically by MotionModule."""

    return MecanumDashboard(module, drive)
