"""The Mecanum robot's MPU9255, wired directly to the Raspberry Pi.

Use the single wiring plan in Debug > Wiring and docs/PINOUT.md:
VCC -> physical 17, GND and AD0 -> 6, SDA -> 11, SCL -> 12.
Enable dtoverlay=i2c-gpio,i2c_gpio_sda=17,i2c_gpio_scl=18 and reboot.
The Pi reads the independent bus; no Arduino is part of this setup.

Additional sensors are not declared. Optional USB GPIO expansion through an
Arduino GIGA R1 WiFi is an experimental extension; see docs/CODING.md.
"""

from motion_module.imu import GigaIMU
from motion_module.telemetry import IMUReading


# GigaIMU is the shared chip-declaration type; this uses the local Pi reader.
IMU = GigaIMU("mpu9255", "Main IMU", address=0x68)


class RobotSensors:
    """One Pi IMU shared by driving, autonomous and the dashboard."""

    def __init__(self, module):
        self.imu = module.local_imu(IMU)

    def heading(self):
        """Degrees from -180 to 180, increasing on a left turn; None offline."""
        return self.imu.heading() if self.imu is not None else None

    def zero_heading(self):
        """Make the way the robot faces now read 0 degrees."""
        if self.imu is not None:
            self.imu.zero()

    def reading(self):
        if self.imu is not None:
            return self.imu.reading()
        return IMUReading(
            name=IMU.name, connected=False, calibrated=False,
            detail="Pi MPU9255 unavailable. On the Pi, enable the i2c-gpio overlay and reboot; see Debug > Wiring.",
        )


def create_sensors(module):
    """Called once by robot.py; MotionModule closes the IMU on shutdown."""
    return RobotSensors(module)
