"""Optional Driver Station telemetry for the Mecanum example.

MotionModule finds this file automatically because it sits beside robot.py.
Delete it and driving still works; edit it when the robot gains cameras, an
IMU, Raspberry Pi digital inputs, or a USB sensor controller.
"""

from motion_module.sensor_bridge import GigaPin, GigaR1Bridge
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
        # GPIO4 is unused by the sample motor map. MotionModule refuses a pin
        # automatically if hardware.py already assigned or reserved it.
        self.forward_limit = module.digital_input(4, pull="up")
        # The GIGA is found automatically by its official USB VID/PID. Flash
        # giga_sensor_bridge.ino once; pin modes below are then sent from this
        # file after every USB reconnect.
        self.giga = GigaR1Bridge([
            GigaPin(
                "A0", "Arm potentiometer", kind="analog", unit="raw",
                minimum=0, maximum=4095,
            ),
            GigaPin("D22", "Intake beam", kind="digital", pull="up"),
        ])

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

    def pi_inputs(self):
        # Raspberry Pi header GPIO has digital input only. Use a USB controller
        # such as the GIGA (below) or an external ADC for analog sensors.
        return [
            SensorReading(
                "Forward limit",
                self.forward_limit.value if self.forward_limit.connected else None,
                kind="digital",
                channel="GPIO4 · pin 7",
                connected=self.forward_limit.connected,
                detail="Normally closed limit switch using the Pi pull-up",
            ),
        ]

    def usb_controllers(self):
        return [self.giga.snapshot()]

    def close(self):
        self.giga.close()


def create_dashboard(module, drive):
    """Optional entry point discovered automatically by MotionModule."""

    return MecanumDashboard(module, drive)
